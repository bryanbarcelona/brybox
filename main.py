import logging
import glob
from brybox import DoctopusPrime
from logging_config import configure_logging
from brybox import enable_verbose_logging
from brybox import DoctopusPrime
from brybox import DoctopusPrimeNexus
from brybox import fetch_and_process_emails, log_and_display
from brybox import DirectoryVerifier

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
    
    # # Process and move file
    # success = processor.shuttle_service(include_backup=True)
    # print(f"Processing success: {success}")

    # verifier = DirectoryVerifier(r"D:\Testing PDFs", r"D:\Testing PDF Target")
    # # Example 2: Batch processing
    # batch_processor = DoctopusPrimeNexus(
    #     dir_path=r"D:\Testing PDFs",
    #     base_dir=r"D:\Testing PDF Target",
    #     dry_run=False
    # )
    
    # results = batch_processor.process_all(include_backup=False)
    # #print(f"Batch processing results: {results}")
    # success = verifier.report()
    # verifier.cleanup()

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


if __name__ == "__main__":
    main()
