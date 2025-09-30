from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import datetime
from pathlib import Path
import logging

from ..utils.health_check import is_pdf_healthy
from ..utils.logging import log_and_display
from .models import DownloadResult

logger = logging.getLogger("WebMarionette")


def download_techem_invoice(user: str, password: str, download_dir: str = None, headless: bool = False) -> DownloadResult:
    """
    Downloads the latest Techem invoice PDF in a headless-safe way.
    Returns DownloadResult with success status and details.
    """
    if download_dir is None:
        download_dir = str(Path.home() / "Downloads")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(download_dir) / f"techem_invoice_{timestamp}.pdf"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(
                viewport={"width": 1280, "height": 1024},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/118.0.5993.90 Safari/537.36",
                device_scale_factor=1,
            )
            page = context.new_page()

            # Navigate with network idle wait
            page.goto("https://mieter.techem.de/", wait_until="networkidle")
            log_and_display("Techem page loaded", log=False, sticky=False)
            
            # Attempt to click cookie banner if visible
            if not headless:
                try:
                    cookie_button = page.get_by_role("button", name="Use necessary cookies only")
                    cookie_button.wait_for(state="visible", timeout=5000)
                    cookie_button.click()
                    log_and_display("Cookie banner accepted", log=False, sticky=False)
                except PlaywrightTimeoutError:
                    log_and_display("Cookie banner not visible, skipping", log=False, sticky=False)
                    pass

            # Login
            login_button = page.get_by_role("button", name="Login").first
            login_button.wait_for(state="visible", timeout=10000)
            login_button.click()
            log_and_display("Login button clicked", log=False, sticky=False)

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
            log_and_display(f"Downloaded: {output_path.name}", log=True, sticky=False)
            return DownloadResult(
                success=True,
                total_found=1,
                downloaded=1,
                failed=0,
                errors=[]
            )
        else:
            error_msg = "PDF failed health check"
            log_and_display(f"Download failed: {error_msg}", level="warning", log=True, sticky=False)
            return DownloadResult(
                success=False,
                total_found=1,
                downloaded=0,
                failed=1,
                errors=[error_msg]
            )

    except PlaywrightTimeoutError as e:
        error_msg = "Timeout while interacting with Techem site"
        log_and_display(f"Download failed: {error_msg}", level="error", log=True, sticky=False)
        return DownloadResult(
            success=False,
            total_found=1,
            downloaded=0,
            failed=1,
            errors=[error_msg]
        )
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        log_and_display(f"Download failed: {error_msg}", level="error", log=True, sticky=False)
        return DownloadResult(
            success=False,
            total_found=1,
            downloaded=0,
            failed=1,
            errors=[error_msg]
        )


def download_kfw_invoices(user: str, password: str, download_dir: str = None, headless: bool = False) -> DownloadResult:
    """
    Downloads all available KFW invoice PDFs using request interception method.
    DOES NOT ARCHIVE DOCUMENTS - only downloads them.
    
    Returns DownloadResult with success status and details.
    """
    if download_dir is None:
        download_dir = str(Path.home() / "Downloads")
    
    errors = []
    
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
            
            # Get all download buttons upfront
            download_buttons = page.locator("input[alt='Dokument anzeigen']").all()
            total_documents = len(download_buttons)
            
            if total_documents == 0:
                log_and_display("No documents found in inbox", log=False, sticky=False)
                browser.close()
                return DownloadResult(
                    success=False,
                    total_found=0,
                    downloaded=0,
                    failed=0,
                    errors=["No documents found in inbox"]
                )
            
            log_and_display(f"Found {total_documents} document(s)", log=False, sticky=False)
            
            success_count = 0
            fail_count = 0
            
            for index, download_button in enumerate(download_buttons, start=1):
                try:
                    log_and_display(f"Processing document {index}/{total_documents}", log=False, sticky=False)
                    
                    # Get document ID from form
                    form = download_button.locator("xpath=ancestor::form[1]")
                    dokid = form.locator("input[name='dokid']").get_attribute("value")
                    
                    captured_request = [None]
                    
                    def capture_request(request):
                        if "KfwFormularServer" in request.url and request.method == "POST":
                            captured_request[0] = request
                    
                    context.on("request", capture_request)
                    download_button.click()
                    
                    # Wait for request capture with polling
                    max_wait_ms = 10000
                    poll_interval_ms = 100
                    elapsed_ms = 0
                    
                    while captured_request[0] is None and elapsed_ms < max_wait_ms:
                        page.wait_for_timeout(poll_interval_ms)
                        elapsed_ms += poll_interval_ms
                    
                    context.remove_listener("request", capture_request)
                    
                    if captured_request[0] is None:
                        error_msg = f"Document {index}: Timeout waiting for request capture"
                        log_and_display(error_msg, level="warning", log=True, sticky=False)
                        errors.append(error_msg)
                        fail_count += 1
                        continue
                    
                    # Replay the exact same request
                    original_request = captured_request[0]
                    
                    response = context.request.post(
                        original_request.url,
                        data=original_request.post_data,
                        headers=original_request.headers
                    )
                    
                    if response.status == 200:
                        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename = f"kfw_document_{index}_{dokid}_{timestamp}.pdf"
                        output_path = Path(download_dir) / filename
                        
                        with open(output_path, "wb") as f:
                            f.write(response.body())
                        
                        log_and_display(f"Downloaded: {filename} ({len(response.body())} bytes)", log=True, sticky=False)
                        success_count += 1
                    else:
                        error_msg = f"Document {index}: HTTP {response.status}"
                        log_and_display(error_msg, level="warning", log=True, sticky=False)
                        errors.append(error_msg)
                        fail_count += 1
                        
                except Exception as e:
                    error_msg = f"Document {index}: {str(e)}"
                    log_and_display(error_msg, level="warning", log=True, sticky=False)
                    errors.append(error_msg)
                    fail_count += 1
                    continue
            
            browser.close()
            
            return DownloadResult(
                success=success_count > 0,
                total_found=total_documents,
                downloaded=success_count,
                failed=fail_count,
                errors=errors
            )
            
    except PlaywrightTimeoutError as e:
        error_msg = "Timeout while interacting with KFW site"
        log_and_display(error_msg, level="error", log=True, sticky=False)
        return DownloadResult(
            success=False,
            total_found=0,
            downloaded=0,
            failed=0,
            errors=[error_msg]
        )
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        log_and_display(error_msg, level="error", log=True, sticky=False)
        return DownloadResult(
            success=False,
            total_found=0,
            downloaded=0,
            failed=0,
            errors=[error_msg]
        )
# def download_techem_invoice(user: str, password: str, download_dir: str = None, headless: bool = False) -> bool:
#     """
#     Downloads the latest Techem invoice PDF in a headless-safe way.
#     Returns True if download succeeded and PDF is healthy, False otherwise.
#     """
#     if download_dir is None:
#         download_dir = str(Path.home() / "Downloads")

#     timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
#     output_path = Path(download_dir) / f"techem_invoice_{timestamp}.pdf"

#     try:
#         with sync_playwright() as playwright:
#             browser = playwright.chromium.launch(headless=headless)  # still works headed
#             context = browser.new_context(
#                 viewport={"width": 1280, "height": 1024},
#                 user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#                         "AppleWebKit/537.36 (KHTML, like Gecko) "
#                         "Chrome/118.0.5993.90 Safari/537.36",
#                 device_scale_factor=1,
#             )
#             page = context.new_page()

#             # Navigate with network idle wait
#             page.goto("https://mieter.techem.de/", wait_until="networkidle")
#             log_and_display("Page loaded", log=False)
#             # Attempt to click cookie banner if visible
#             if not headless:
#                 try:
#                     cookie_button = page.get_by_role("button", name="Use necessary cookies only")
#                     cookie_button.wait_for(state="visible", timeout=5000)
#                     cookie_button.click()
#                     log_and_display("Cookie banner accepted", log=False)
#                 except PlaywrightTimeoutError:
#                     log_and_display("Cookie banner not visible, skipping.")
#                     pass

#             # Login
#             login_button = page.get_by_role("button", name="Login").first
#             login_button.wait_for(state="visible", timeout=10000)
#             login_button.click()
#             log_and_display("Login button clicked", log=False)

#             page.fill("#signInName", user)
#             page.fill("#password", password)
#             page.click("#next")

#             # Wait for PDF button and download
#             pdf_button = page.get_by_role("button", name="PDF herunterladen")
#             pdf_button.wait_for(state="visible", timeout=15000)

#             with page.expect_download() as download_info:
#                 pdf_button.click()

#             download = download_info.value
#             download.save_as(str(output_path))
#             browser.close()

#         # Verify PDF health
#         if is_pdf_healthy(output_path):
#             log_and_display(f"PDF downloaded and verified: {output_path}", log=False)
#             return True
#         else:
#             log_and_display(f"PDF downloaded but failed health check: {output_path}", level="warning")
#             return False

#     except PlaywrightTimeoutError as e:
#         log_and_display("Timeout while interacting with Techem site", level="error")
#         return False
#     except Exception as e:
#         log_and_display("Unexpected error during Techem download", level="error")
#         return False

# def download_kfw_invoices(user: str, password: str, download_dir: str = None, headless: bool = False) -> bool:
#     """
#     Downloads all available KFW invoice PDFs using request interception method.
#     DOES NOT ARCHIVE DOCUMENTS - only downloads them.
    
#     Returns True if at least one download succeeded, False otherwise.
#     """
#     if download_dir is None:
#         download_dir = str(Path.home() / "Downloads")
    
#     try:
#         with sync_playwright() as playwright:
#             browser = playwright.chromium.launch(headless=headless)
#             context = browser.new_context(accept_downloads=True)
#             page = context.new_page()
            
#             # Login to KFW portal
#             page.goto("https://onlinekreditportal.kfw.de/BK_KNPlattform/KfwFormularServer")
            
#             # Fill username and password
#             page.fill("#BANKING_ID", user)
#             page.fill("#PIN", password)
            
#             # Click the submit button
#             page.click("input[name='login'][type='submit']")
            
#             # Wait for navigation
#             page.wait_for_load_state("networkidle")
            
#             # Navigate to postbox
#             page.goto("https://onlinekreditportal.kfw.de/BK_KNPlattform/KfwFormularServer/BK_KNPlattform/PostkorbEingangBrowseAction")
            
#             # Get all download buttons upfront
#             download_buttons = page.locator("input[alt='Dokument anzeigen']").all()
#             total_documents = len(download_buttons)
            
#             if total_documents == 0:
#                 log_and_display("No documents found in inbox", log=False)
#                 browser.close()
#                 return False
            
#             log_and_display(f"Found {total_documents} document(s) to download", log=False)
            
#             success_count = 0
#             fail_count = 0
            
#             for index, download_button in enumerate(download_buttons, start=1):
#                 try:
#                     log_and_display(f"Processing document {index}/{total_documents}", log=False)
                    
#                     # Get document ID from form
#                     form = download_button.locator("xpath=ancestor::form[1]")
#                     dokid = form.locator("input[name='dokid']").get_attribute("value")
                    
#                     captured_request = [None]
                    
#                     def capture_request(request):
#                         if "KfwFormularServer" in request.url and request.method == "POST":
#                             captured_request[0] = request
                    
#                     context.on("request", capture_request)
#                     download_button.click()
                    
#                     # Wait for request capture with polling
#                     max_wait_ms = 10000  # 10 seconds should handle slow connections
#                     poll_interval_ms = 100
#                     elapsed_ms = 0
                    
#                     while captured_request[0] is None and elapsed_ms < max_wait_ms:
#                         page.wait_for_timeout(poll_interval_ms)
#                         elapsed_ms += poll_interval_ms
                    
#                     context.remove_listener("request", capture_request)
                    
#                     if captured_request[0] is None:
#                         log_and_display(f"Timeout: no request captured after {max_wait_ms/1000}s for document {index}")
#                         fail_count += 1
#                         continue
                    
#                     # Replay the exact same request
#                     original_request = captured_request[0]
                    
#                     response = context.request.post(
#                         original_request.url,
#                         data=original_request.post_data,
#                         headers=original_request.headers
#                     )
                    
#                     if response.status == 200:
#                         timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
#                         filename = f"kfw_document_{index}_{dokid}_{timestamp}.pdf"
#                         output_path = Path(download_dir) / filename
                        
#                         with open(output_path, "wb") as f:
#                             f.write(response.body())
                        
#                         log_and_display(f"Downloaded: {filename} ({len(response.body())} bytes)")
#                         success_count += 1
#                     else:
#                         log_and_display(f"Request failed with status: {response.status}")
#                         fail_count += 1
                        
#                 except Exception as e:
#                     log_and_display(f"Error processing document {index}: {e}")
#                     fail_count += 1
#                     continue
            
#             browser.close()
            
#             log_and_display(
#                 f"Download completed. Success: {success_count}, Failed: {fail_count}, Total: {total_documents}",
#                 log=False
#             )
#             return success_count > 0
            
#     except PlaywrightTimeoutError as e:
#         log_and_display("Timeout while interacting with KFW site", level="error")
#         return False
#     except Exception as e:
#         log_and_display("Unexpected error during KFW download", level="error")
#         return False
    
            
if __name__ == "__main__":

    pass