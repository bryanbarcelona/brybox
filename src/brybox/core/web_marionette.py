import os
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import datetime
from dotenv import load_dotenv
from dataclasses import dataclass
from .doctopus import DoctopusPrime
from pathlib import Path
import logging
#from logging_config import configure_logging
from ..utils.health_check import is_pdf_healthy
from ..utils.logging import log_and_display

#configure_logging()
logger = logging.getLogger("WebMarionette")


def download_techem_invoice(user: str, password: str, download_dir: str = None, headless: bool = False) -> bool:
    """
    Downloads the latest Techem invoice PDF in a headless-safe way.
    Returns True if download succeeded and PDF is healthy, False otherwise.
    """
    if download_dir is None:
        download_dir = str(Path.home() / "Downloads")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(download_dir) / f"techem_invoice_{timestamp}.pdf"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)  # still works headed
            context = browser.new_context(
                viewport={"width": 1280, "height": 1024},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/118.0.5993.90 Safari/537.36",
                device_scale_factor=1,
            )
            page = context.new_page()

            # Move the browser window off-screen (Windows)
            # page.evaluate("""
            #     window.moveTo(-20000, -20000);
            #     window.resizeTo(1280, 1024);
            # """)

            # Navigate with network idle wait
            page.goto("https://mieter.techem.de/", wait_until="networkidle")
            log_and_display("Page loaded", log=False)
            # Attempt to click cookie banner if visible
            if not headless:
                try:
                    cookie_button = page.get_by_role("button", name="Use necessary cookies only")
                    cookie_button.wait_for(state="visible", timeout=5000)
                    cookie_button.click()
                    log_and_display("Cookie banner accepted", log=False)
                except PlaywrightTimeoutError:
                    log_and_display("Cookie banner not visible, skipping.")
                    pass

            # Login
            login_button = page.get_by_role("button", name="Login").first
            login_button.wait_for(state="visible", timeout=10000)
            login_button.click()
            log_and_display("Login button clicked", log=False)

            page.fill("#signInName", user)
            page.fill("#password", password)
            page.click("#next")

            # Wait for PDF button and download
            pdf_button = page.get_by_role("button", name="PDF herunterladen")
            pdf_button.wait_for(state="visible", timeout=15000)

            with page.expect_download() as download_info:
                pdf_button.click()

            download = download_info.value
            download.save_as(str(output_path))
            browser.close()

        # Verify PDF health
        if is_pdf_healthy(output_path):
            log_and_display(f"PDF downloaded and verified: {output_path}", log=False)
            return True
        else:
            log_and_display(f"PDF downloaded but failed health check: {output_path}", level="warning")
            return False

    except PlaywrightTimeoutError as e:
        log_and_display("Timeout while interacting with Techem site", level="error")
        return False
    except Exception as e:
        log_and_display("Unexpected error during Techem download", level="error")
        return False

def download_kfw_invoices(user: str, password: str, download_dir: str = None, headless: bool = False) -> bool:
    """
    Downloads all available KFW invoice PDFs using request interception method.
    DOES NOT ARCHIVE DOCUMENTS - only downloads them.
    
    Returns True if at least one download succeeded, False otherwise.
    """
    if download_dir is None:
        download_dir = str(Path.home() / "Downloads")

    download_count = 0
    
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            
            # Login to KFW portal
            page.goto("https://onlinekreditportal.kfw.de/BK_KNPlattform/KfwFormularServer")
            
            # Fill username and password
            page.fill("#BANKING_ID", user)
            page.fill("#PIN", password)
            
            # Click the submit button
            page.click("input[name='login'][type='submit']")
            
            # Wait for navigation
            page.wait_for_load_state("networkidle")
            
            # Navigate to postbox
            page.goto("https://onlinekreditportal.kfw.de/BK_KNPlattform/KfwFormularServer/BK_KNPlattform/PostkorbEingangBrowseAction")
            
            count = 0
            while count < 1:
                try:
                    # Find the first visible download button
                    download_button = page.locator("input[alt='Dokument anzeigen']").first
                    
                    if not download_button.is_visible():
                        log_and_display("No more download buttons found. Stopping.", log=False)
                        break

                    count += 1
                    log_and_display(f"Processing document {count}", log=False)

                    # Get document ID from form
                    form = download_button.locator("xpath=ancestor::form[1]")
                    dokid = form.locator("input[name='dokid']").get_attribute("value")
                    
                    captured_request = [None]
                    
                    def capture_request(request):
                        if "KfwFormularServer" in request.url and request.method == "POST":
                            captured_request[0] = request
                            log_and_display(f"Captured POST request for document {dokid}", log=False)
                    
                    context.on("request", capture_request)
                    
                    # Click the button to capture the exact request
                    download_button.click()
                    
                    # Wait for the request to be captured
                    page.wait_for_timeout(3000)
                    
                    context.remove_listener("request", capture_request)
                    
                    if captured_request[0]:
                        # Replay the exact same request
                        original_request = captured_request[0]
                        
                        response = context.request.post(
                            original_request.url,
                            data=original_request.post_data,
                            headers=original_request.headers
                        )
                        
                        if response.status == 200:
                            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = f"kfw_document_{count}_{dokid}_{timestamp}.pdf"
                            output_path = Path(download_dir) / filename
                            
                            with open(output_path, "wb") as f:
                                f.write(response.body())
                            
                            log_and_display(f"Downloaded: {filename} ({len(response.body())} bytes)")
                            download_count += 1
                            
                            # NO ARCHIVING - DOCUMENT REMAINS IN INBOX
                        else:
                            log_and_display(f"Request failed with status: {response.status}")
                            break
                    else:
                        log_and_display("No POST request captured")
                        break
                        
                except PlaywrightTimeoutError:
                    log_and_display("Timeout occurred, continuing to next document")
                    continue
                except Exception as e:
                    log_and_display(f"Error processing document {count}: {e}")
                    continue
            
            browser.close()
            
        log_and_display(f"Download completed. Total documents downloaded: {download_count}", log=False)
        return download_count > 0
        
    except PlaywrightTimeoutError as e:
        log_and_display("Timeout while interacting with KFW site")
        return False
    except Exception as e:
        log_and_display("Unexpected error during KFW download")
        return False


def download_kfw_single_document(page, context, download_button, download_dir: str, doc_number: int) -> bool:
    """
    Helper function to download a single KFW document.
    DOES NOT ARCHIVE - only downloads the document.
    Returns True if successful, False otherwise.
    """
    try:
        if not download_button.is_visible():
            return False
            
        # Get document ID from form
        form = download_button.locator("xpath=ancestor::form[1]")
        dokid = form.locator("input[name='dokid']").get_attribute("value")
        
        captured_request = [None]
        
        def capture_request(request):
            if "KfwFormularServer" in request.url and request.method == "POST":
                captured_request[0] = request
                log_and_display(f"Captured POST request for document {dokid}", log=False)
        
        context.on("request", capture_request)
        
        # Click the button to capture the exact request
        download_button.click()
        
        # Wait for the request to be captured
        page.wait_for_timeout(3000)
        
        context.remove_listener("request", capture_request)
        
        if captured_request[0]:
            # Replay the exact same request
            original_request = captured_request[0]
            
            response = context.request.post(
                original_request.url,
                data=original_request.post_data,
                headers=original_request.headers
            )
            
            if response.status == 200:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"kfw_document_{doc_number}_{dokid}_{timestamp}.pdf"
                output_path = Path(download_dir) / filename
                
                with open(output_path, "wb") as f:
                    f.write(response.body())
                
                log_and_display(f"Downloaded: {filename} ({len(response.body())} bytes)")
                return True
            else:
                log_and_display(f"Request failed with status: {response.status}")
                return False
        else:
            log_and_display("No POST request captured")
            return False
            
    except Exception as e:
        log_and_display(f"Error downloading document: {e}")
        return False
            
if __name__ == "__main__":

    pass