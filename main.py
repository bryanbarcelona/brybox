import logging
import glob
from pathlib import Path
from brybox import DoctopusPrime
from logging_config import configure_logging
from brybox import enable_verbose_logging
from brybox import DoctopusPrime
from brybox import DoctopusPrimeNexus
from brybox import fetch_and_process_emails, log_and_display
from brybox import DirectoryVerifier
from brybox import push_photos

logger = logging.getLogger("BryBox")

def main():
    # print("IN MAIN: root handlers =", len(logging.getLogger().handlers))
    configure_logging()
    enable_verbose_logging()

    #logger.setLevel(logging.INFO)
    # logger.info("Logging is configured.")
    log_and_display("Logging is configured.", sticky=True)

    # # # Example 1: Single PDF processing
    # # processor = DoctopusPrime2(
    # #     pdf_filepath=r"D:\Testing PDFs\document_2_1132426471.pdf",
    # #     base_dir=r"D:\Testing PDF Target",
    # #     dry_run=False
    # # )
    
    # Process and move file
    # success = processor.shuttle_service(include_backup=True)
    # print(f"Processing success: {success}")

    verifier = DirectoryVerifier(r"D:\Testing PDFs", r"D:\Testing PDF Target")
    # Example 2: Batch processing
    batch_processor = DoctopusPrimeNexus(
        dir_path=r"D:\Testing PDFs",
        base_dir=r"D:\Testing PDF Target",
        dry_run=False
    )
    
    results = batch_processor.process_all(include_backup=False)
    #print(f"Batch processing results: {results}")
    success = verifier.report()
    verifier.cleanup()

    fetch_and_process_emails()

    log_and_display("Finished all tasks.", sticky=True)
    # print("BEFORE DoctopusPrime: root handlers =", len(logging.getLogger().handlers))

    # pdfs = glob.glob(r"C:\Users\bryan\Downloads\*.pdf")

    # for pdf in pdfs:
    #     print(f"{"_"*20}")
    #     print(pdf)
    #     current = DoctopusPrime(pdf)


    # doc = DoctopusPrime(r"C:\Users\bryan\Downloads\kfw_document_1_1132426471_20250906_231540.pdf")
    # from brybox import inbox_kraken
    # #inbox_kraken.fetch_and_process_emails()

def test_pixelporter():
    """Test photo ingestion with verification."""
    
    # Define paths (adjust to your test directories)
    source_dir = Path(r"d:\\PixelporterTest\\20251003\\src")
    target_dir = Path(r"d:\\PixelporterTest\\20251003\\dst")

    # Initialize verifier
    verifier = DirectoryVerifier(str(source_dir), str(target_dir))
    
    # Run PixelPorter (dry run first)
    print("=== DRY RUN ===")
    result = push_photos(
        source=source_dir,
        target=target_dir,
        dry_run=True
    )
    
    print(f"\nDry run results: Processed={result.processed}, Skipped={result.skipped}, Failed={result.failed}")
    
    # Real run
    print("\n=== REAL RUN ===")
    result = push_photos(
        source=source_dir,
        target=target_dir,
        dry_run=False
    )
    
    print(f"\nReal run results: Processed={result.processed}, Skipped={result.skipped}, Failed={result.failed}")
    
    # Verify
    print("\n=== VERIFICATION ===")
    success = verifier.report()
    verifier.cleanup()
    
    if not success:
        print("❌ Verification failed!")
        return False
    
    print("✅ All operations verified successfully")
    return True

if __name__ == "__main__":
    #main()
    test_pixelporter()
