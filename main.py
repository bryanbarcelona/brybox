import logging
from pathlib import Path

from brybox import (
    AudioraNexus,
    DirectoryVerifier,
    DoctopusPrimeNexus,
    VideoSith,
    enable_verbose_logging,
    #fetch_and_process_emails,
    log_and_display,
    push_photos,
    push_videos,
    InboxKraken
)
from logging_config import configure_logging
from test_env_resetter import testing_doctopus

logger = logging.getLogger('BryBox')


def main():
    # print("IN MAIN: root handlers =", len(logging.getLogger().handlers))
    configure_logging()
    enable_verbose_logging()

    # logger.setLevel(logging.INFO)
    # logger.info("Logging is configured.")
    log_and_display('Logging is configured.', sticky=True)

    # # # Example 1: Single PDF processing
    # # processor = DoctopusPrime2(
    # #     pdf_filepath=r"D:\Testing PDFs\document_2_1132426471.pdf",
    # #     base_dir=r"D:\Testing PDF Target",
    # #     dry_run=False
    # # )

    # Process and move file
    # success = processor.shuttle_service(include_backup=True)
    # print(f"Processing success: {success}")

    verifier = DirectoryVerifier(r'D:\Testing PDFs', r'D:\Testing PDF Target')
    # Example 2: Batch processing
    batch_processor = DoctopusPrimeNexus(dir_path=r'D:\Testing PDFs', base_dir=r'D:\Testing PDF Target', dry_run=False)

    results = batch_processor.process_all(include_backup=False)
    # print(f"Batch processing results: {results}")
    success = verifier.report()
    verifier.cleanup()

    #fetch_and_process_emails()

    log_and_display('Finished all tasks.', sticky=True)
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

    configure_logging()
    enable_verbose_logging()

    # logger.setLevel(logging.INFO)
    # logger.info("Logging is configured.")
    log_and_display('Logging is configured.', sticky=True)

    # Define paths (adjust to your test directories)
    source_dir = Path(r'D:\BryBoxTesting\PixelporterTest\20251003\src')
    target_dir = Path(r'D:\BryBoxTesting\PixelporterTest\20251003\dst')

    # Initialize verifier
    verifier = DirectoryVerifier(str(source_dir), str(target_dir))

    # Run PixelPorter (dry run first)
    print('=== DRY RUN ===')
    result = push_photos(
        # source=source_dir,
        # target=target_dir,
        dry_run=True
    )

    print(f'\nDry run results: Processed={result.processed}, Skipped={result.skipped}, Failed={result.failed}')

    # Real run
    print('\n=== REAL RUN ===')
    result = push_photos(
        # source=source_dir,
        # target=target_dir,
        dry_run=False
    )

    print(f'\nReal run results: Processed={result.processed}, Skipped={result.skipped}, Failed={result.failed}')

    result = push_videos(
        # source=source_dir,
        # target=target_dir,
        dry_run=False
    )

    print(f'\nReal run results: Processed={result.processed}, Skipped={result.skipped}, Failed={result.failed}')

    # Verify
    print('\n=== VERIFICATION ===')
    success = verifier.report()
    verifier.cleanup()

    if not success:
        print('❌ Verification failed!')
        return False

    print('✅ All operations verified successfully')
    return True


def test_videosith():
    """Test video processing with VideoSith."""

    configure_logging()
    enable_verbose_logging()

    log_and_display('Logging is configured.', sticky=True)

    processor = VideoSith()

    # Process a MOV file
    mov_path = Path(r'D:\BryBoxTesting\VideoSithTest\src\Disneyland_134.3gp')

    if mov_path.exists():
        processor.file_path = mov_path
        success = processor.convert_to_mp4()
        processor.rename_mp4()
        if success:
            log_and_display(f'✅ Video processed successfully: {mov_path.name}', sticky=True)
        else:
            log_and_display(f'❌ Video processing failed: {mov_path.name}', sticky=True)
    else:
        log_and_display(f'❌ Video file does not exist: {mov_path}', sticky=True)


def test_audiora():

    configure_logging()
    enable_verbose_logging()

    # logger.setLevel(logging.INFO)
    # logger.info("Logging is configured.")
    log_and_display('Logging is configured.', sticky=True)

    # # # Example 1: Single PDF processing
    # # processor = DoctopusPrime2(
    # #     pdf_filepath=r"D:\Testing PDFs\document_2_1132426471.pdf",
    # #     base_dir=r"D:\Testing PDF Target",
    # #     dry_run=False
    # # )

    # Process and move file
    # success = processor.shuttle_service(include_backup=True)
    # print(f"Processing success: {success}")

    audio_source_dir = r'C:\Users\bryan\Downloads\Chuck McGee - Copy'
    audio_target_dir = r'C:\Users\bryan\Downloads\Audio'

    verifier = DirectoryVerifier(audio_source_dir, audio_target_dir)
    # Example 2: Batch processing
    nexus_real = AudioraNexus(
        dir_path=audio_source_dir, base_dir=audio_target_dir, config_path='configs', dry_run=False
    )
    results_real = nexus_real.process_all(progress_bar=True)

    success = verifier.report()
    verifier.cleanup()

    # fetch_and_process_emails()

    log_and_display('Finished all tasks.', sticky=True)


def test_inbox_kraken():
    configure_logging()
    enable_verbose_logging()

    #fetch_and_process_emails()

def test_doctopus():
    # Clean up testing environment

    configure_logging()
    enable_verbose_logging()
    log_and_display('Logging is configured.', sticky=True)

    log_and_display("🚀 Starting Doctopus Smoke Test...")

    testing_doctopus()

    verifier = DirectoryVerifier(
        r"D:\BryBoxTesting\DoctopusTest\src", r"D:\BryBoxTesting\DoctopusTest\dst"
    )
    # Example 2: Batch processing
    batch_processor = DoctopusPrimeNexus(
        dir_path=r"D:\BryBoxTesting\DoctopusTest\src",
        base_dir=r"D:\BryBoxTesting\DoctopusTest\dst",
        dry_run=False,
    )

    results = batch_processor.process_all()
    # print(f"Batch processing results: {results}")
    success = verifier.report()
    verifier.cleanup()


def full_run_test():

    SAMPLE_EMAIL_UIDS = [
        43661, # delete - Lina Hildebrandt
        43512, # audio - Chuck
        43674, # PDF link - Bolt
        43672, # Techem
        43560, # KfW
        43829, # Stoklossa
    ]
    configure_logging()
    enable_verbose_logging()
    log_and_display('Logging is configured.', sticky=True)

    log_and_display("🚀 Starting Kraken Smoke Test...")

    #fetch_and_process_emails()

    with InboxKraken(dry_run=True) as kraken:
            
        # Scenario A: Test against specific UIDs you know have attachments or links
        # targeted_uids = [12345, 12346]
        # kraken.run(only_uids=targeted_uids)

        # Scenario B: Just run against the last 10 emails in the inbox
        #log_and_display("Running against the last 10 emails...")
        kraken.run(only_uids=SAMPLE_EMAIL_UIDS)

        log_and_display("✅ Smoke test complete. Check the logs above for [DRY RUN] messages.")    

    verifier = DirectoryVerifier(
        r'C:\\Users\\Bryan\\Downloads\\TempInvoices20260224', r'C:\\Users\\Bryan\\Downloads\\sortedTempInvoices20260224'
    )
    # Example 2: Batch processing
    batch_processor = DoctopusPrimeNexus(
        dir_path=r'C:\\Users\\Bryan\\Downloads\\TempInvoices20260224',
        base_dir=r'C:\Users\Bryan\Downloads\sortedTempInvoices20260224',
        dry_run=False,
    )

    results = batch_processor.process_all(include_backup=False)
    # print(f"Batch processing results: {results}")
    success = verifier.report()
    verifier.cleanup()

    audio_source_dir = r'C:\Users\bryan\Downloads\TempInvoices20260224'
    audio_target_dir = r'C:\Users\bryan\Downloads\Audio20260224'

    verifier = DirectoryVerifier(audio_source_dir, audio_target_dir)
    # Example 2: Batch processing
    nexus_real = AudioraNexus(
        dir_path=audio_source_dir, base_dir=audio_target_dir, dry_run=False
    )
    results_real = nexus_real.process_all(progress_bar=True)

    success = verifier.report()
    verifier.cleanup()

    #test_pixelporter()

if __name__ == '__main__':
    # main()
    # test_pixelporter()
    # test_videosith()
    # test_audiora()
    # test_inbox_kraken()
    # full_run_test()
    test_doctopus()
