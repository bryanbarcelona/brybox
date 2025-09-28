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

#configure_logging()
logger = logging.getLogger("WebMarionette")

load_dotenv()

USER_MAIN = os.getenv("USER_MAIN")
TECHEM_PWD = os.getenv("TECHEM_PWD")

USER_KFW = os.getenv("USER_KFW")
KFW_PWD = os.getenv("KFW_PWD")


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
            print("Page loaded")
            # Attempt to click cookie banner if visible
            if not headless:
                try:
                    cookie_button = page.get_by_role("button", name="Use necessary cookies only")
                    cookie_button.wait_for(state="visible", timeout=5000)
                    cookie_button.click()
                    print("Cookie banner accepted")
                except PlaywrightTimeoutError:
                    print("Cookie banner not visible, skipping.")
                    pass

            # Login
            login_button = page.get_by_role("button", name="Login").first
            login_button.wait_for(state="visible", timeout=10000)
            login_button.click()
            print("Login button clicked")

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
            logger.info(f"PDF downloaded and verified: {output_path}")
            return True
        else:
            logger.warning(f"PDF downloaded but failed health check: {output_path}")
            return False

    except PlaywrightTimeoutError as e:
        logger.exception("Timeout while interacting with Techem site")
        return False
    except Exception as e:
        logger.exception("Unexpected error during Techem download")
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
                        print("No more download buttons found. Stopping.")
                        break

                    count += 1
                    print(f"Processing document {count}")

                    # Get document ID from form
                    form = download_button.locator("xpath=ancestor::form[1]")
                    dokid = form.locator("input[name='dokid']").get_attribute("value")
                    
                    captured_request = [None]
                    
                    def capture_request(request):
                        if "KfwFormularServer" in request.url and request.method == "POST":
                            captured_request[0] = request
                            print(f"Captured POST request for document {dokid}")
                    
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
                            
                            print(f"Downloaded: {filename} ({len(response.body())} bytes)")
                            download_count += 1
                            
                            # NO ARCHIVING - DOCUMENT REMAINS IN INBOX
                        else:
                            print(f"Request failed with status: {response.status}")
                            break
                    else:
                        print("No POST request captured")
                        break
                        
                except PlaywrightTimeoutError:
                    print("Timeout occurred, continuing to next document")
                    continue
                except Exception as e:
                    print(f"Error processing document {count}: {e}")
                    continue
            
            browser.close()
            
        print(f"Download completed. Total documents downloaded: {download_count}")
        return download_count > 0
        
    except PlaywrightTimeoutError as e:
        print("Timeout while interacting with KFW site")
        return False
    except Exception as e:
        print("Unexpected error during KFW download")
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
                print(f"Captured POST request for document {dokid}")
        
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
                
                print(f"Downloaded: {filename} ({len(response.body())} bytes)")
                return True
            else:
                print(f"Request failed with status: {response.status}")
                return False
        else:
            print("No POST request captured")
            return False
            
    except Exception as e:
        print(f"Error downloading document: {e}")
        return False
            
if __name__ == "__main__":

    # success = download_techem_invoice(USER_MAIN, TECHEM_PWD, rf"C:\Users\bryan\Downloads")
    # if success:
    #     print("Download and verification successful. Safe to delete email.")
    # else:
    #     print("Download failed or PDF corrupted. Retry needed.")

    success = download_kfw_invoices(USER_KFW, KFW_PWD, rf"C:\Users\bryan\Downloads", headless=False)
    if success:
        print("KFW download completed successfully")
    else:
        print("KFW download failed")



    # download_dir = rf"C:\Users\bryan\Downloads"
    # playwright = sync_playwright().start()
    # browser = playwright.chromium.launch(headless=False)
    # context = browser.new_context(accept_downloads=True)

    # page = context.new_page()
    # page.goto("https://onlinekreditportal.kfw.de/BK_KNPlattform/KfwFormularServer")

    # # Fill username and password
    # page.fill("#BANKING_ID", USER_KFW)
    # page.fill("#PIN", KFW_PWD)

    # # Click the submit button
    # page.click("input[name='login'][type='submit']")

    # # Optionally wait for navigation or some element on the next page
    # page.wait_for_load_state("networkidle")

    # page.goto("https://onlinekreditportal.kfw.de/BK_KNPlattform/KfwFormularServer/BK_KNPlattform/PostkorbEingangBrowseAction")

    # count = 0
    # while True:
    #     try:
    #         # Find the first visible buttons
    #         download_button = page.locator("input[alt='Dokument anzeigen']").first
    #         archive_button = page.locator("input[alt='Dokument archivieren']").first

    #         if not download_button.is_visible():
    #             print("No more download buttons found. Stopping.")
    #             break

    #         count += 1

    #         # Highlight both
    #         #download_button.wait_for(state="visible")
    #         #download_button.click()
    #         print("Download button located")

    #         form = download_button.locator("xpath=ancestor::form[1]")
    #         dokid = form.locator("input[name='dokid']").get_attribute("value")
            
    #         captured_request = [None]
            
    #         def capture_request(request):
    #             if "KfwFormularServer" in request.url and request.method == "POST":
    #                 captured_request[0] = request
    #                 print(f"Captured POST request to: {request.url}")
    #                 print(f"Headers: {request.headers}")
    #                 print(f"Post data: {request.post_data}")
            
    #         context.on("request", capture_request)
            
    #         # Click the button to capture the exact request
    #         download_button.click()
            
    #         # Wait for the request to be captured
    #         page.wait_for_timeout(3000)
            
    #         context.remove_listener("request", capture_request)
            
    #         if captured_request[0]:
    #             # Replay the exact same request
    #             original_request = captured_request[0]
                
    #             response = context.request.post(
    #                 original_request.url,
    #                 data=original_request.post_data,
    #                 headers=original_request.headers
    #             )
                
    #             print(f"Replayed request status: {response.status}")
    #             print(f"Content length: {len(response.body())}")
                
    #             if response.status == 200:
    #                 with open(rf"{download_dir}\document_{count}_{dokid}.pdf", "wb") as f:
    #                     f.write(response.body())
    #                 print(f"Downloaded: document_{count}_{dokid}.pdf")
    #     except PlaywrightTimeoutError:
    #         pass

    #         input("Press Enter to continue...")
    #         download.save_as(rf"C:\Users\bryan\Downloads\document_{count}.pdf")
    #         print(f"Downloaded: document_{count}.pdf")
    #         input("Press Enter to continue...")
    #         with context.expect_page(timeout=30000) as new_page_info:
    #             download_button.wait_for(state="visible")
    #             download_button.click()

    #             page.wait_for_timeout(2000)  # Short wait for tab to open

    #             # Handle the new tab
    #             new_page = new_page_info.value
    #             print(f"New tab opened: {new_page.url}")
    #             download_pdf = new_page.locator("cr-icon-button#save")
    #             if not download_pdf.is_visible():
    #                 print(f"Download button not visible in new tab for document {count}.")
    #                 new_page.close()
    #             elif download_pdf.is_visible():
    #                 print(f"Download button located in new tab for document {count}. Clicking to download.")
                
    #             input("Press Enter to click download...")
    #             download_pdf.click()
    #             # Save new tab content for debugging
    #             # with open(f"new_tab_{count}.html", "w", encoding="utf-8") as f:
    #             #     f.write(new_page.content())
    #             # print(f"Saved new tab content to new_tab_{count}.html")

    #             # Click the PDF viewer's download button
    #             try:
    #                 with new_page.expect_download(timeout=30000) as download_info:
    #                     new_page.locator("cr-icon-button#save").wait_for(state="visible")
    #                     new_page.locator("cr-icon-button#save").click()
    #                     download = download_info.value
    #                     # Save the downloaded file
    #                     output_path = Path(f"downloaded_pdf_{count}.pdf")
    #                     download.save_as(output_path)
    #                     print(f"PDF saved to {output_path}")
    #             except PlaywrightTimeoutError as e:
    #                 print(f"Failed to find download button or trigger download for document {count}: {str(e)}")
    #             except Exception as e:
    #                 print(f"Error downloading PDF {count}: {str(e)}")

    #             # Close the new tab
    #             new_page.close()
    #         input("Press Enter to continue...")

    #         with page.expect_popup() as popup_info:
    #             download_button.click()
    #         pdf_page = popup_info.value
    #         print(pdf_page)
    #         input("Press Enter to continue...")
    #         print("Popup URL:", pdf_page.url)
    #         # Look for embed or iframe that loads a PDF
    #         pdf_embed = pdf_page.locator("embed[type='application/pdf'], iframe[src*='.pdf']").first

    #         if pdf_embed.is_visible():
    #             pdf_url = pdf_embed.get_attribute("src")
    #             print("Direct PDF URL:", pdf_url)
    #         else:
    #             print("No <embed> or <iframe> with PDF found. Try checking network requests.")

    #         pdf_bytes = pdf_page.pdf(format="A4")  # captures the page as PDF
    #         with open("document.pdf", "wb") as f:
    #             f.write(pdf_bytes)

    #         archive_button.highlight()

    #         # Print once per iteration
    #         print(f"[HIGHLIGHT] Row {count}: would download + archive")

    #         # Pause so you can see highlights
    #         time.sleep(10)

    #     except PlaywrightTimeoutError:
    #         print("Timeout locating buttons. Stopping.")
    #         break

    # print(f"Dry-run finished. Found {count} row(s).")

    # input("BREAK")
    # page.get_by_role("button", name="Use necessary cookies only").click()

    # login_button = page.get_by_role("button", name="Login").first
    # login_button.wait_for(state="visible")
    # login_button.click()

    # page.fill("#signInName", USER_MAIN)

    # page.fill("#password", TECHEM_PWD)

    # page.click("#next")

    # pdf_button = page.get_by_role("button", name="PDF herunterladen")
    # pdf_button.wait_for(state="visible")

    # with page.expect_download() as download_info:
    #     pdf_button.click()

    # timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # download = download_info.value
    # output_path = rf"C:\Users\bryan\Downloads\techem_invoice_{timestamp}.pdf"
    # download.save_as(output_path)

    # print("Saved PDF at:", output_path)

    # browser.close()
    # playwright.stop()
