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
from brybox import push_photos, push_videos
from brybox import SnapJedi
from brybox import VideoSith
from brybox import AudioraCore, AudioraNexus

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
    
    configure_logging()
    enable_verbose_logging()

    #logger.setLevel(logging.INFO)
    # logger.info("Logging is configured.")
    log_and_display("Logging is configured.", sticky=True)

    # Define paths (adjust to your test directories)
    source_dir = Path(r"D:\BryBoxTesting\PixelporterTest\20251003\src")
    target_dir = Path(r"D:\BryBoxTesting\PixelporterTest\20251003\dst")

    # Initialize verifier
    verifier = DirectoryVerifier(str(source_dir), str(target_dir))
    
    # Run PixelPorter (dry run first)
    print("=== DRY RUN ===")
    result = push_photos(
        #source=source_dir,
        #target=target_dir,
        dry_run=True
    )
    
    print(f"\nDry run results: Processed={result.processed}, Skipped={result.skipped}, Failed={result.failed}")
    
    # Real run
    print("\n=== REAL RUN ===")
    result = push_photos(
        #source=source_dir,
        #target=target_dir,
        dry_run=False
    )

    print(f"\nReal run results: Processed={result.processed}, Skipped={result.skipped}, Failed={result.failed}")
    
    result = push_videos(
        # source=source_dir,
        # target=target_dir,
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

def test_videosith():
    """Test video processing with VideoSith."""
    
    configure_logging()
    enable_verbose_logging()

    log_and_display("Logging is configured.", sticky=True)

    processor = VideoSith()
    
    # Process a MOV file
    mov_path = Path(r"D:\BryBoxTesting\VideoSithTest\src\Disneyland_134.3gp")
    
    if mov_path.exists():
        processor.file_path = mov_path
        success = processor.convert_to_mp4()
        processor.rename_mp4()
        if success:
            log_and_display(f"✅ Video processed successfully: {mov_path.name}", sticky=True)
        else:
            log_and_display(f"❌ Video processing failed: {mov_path.name}", sticky=True)
    else:
        log_and_display(f"❌ Video file does not exist: {mov_path}", sticky=True)

def test_audiora():

    
    # print("\n" + "="*60)
    # print("AUDIORA TEST")
    # print("="*60 + "\n")
    
    # # Test directory from your config
    # test_dir = r"C:\Users\bryan\Downloads\Chuck McGee"
    
    # # Test 1: Single file processing
    # print("TEST 1: Single File Processing")
    # print("-" * 40)
    
    # # Get first audio file from test directory
    # import glob
    # audio_files = glob.glob(f"{test_dir}/*.m4a")
    
    # if not audio_files:
    #     print(f"No .m4a files found in {test_dir}")
    #     return
    

    # for test_file in audio_files:
    #     #test_file = audio_files[0]
    #     print("\n" + "-"*40)
    #     print(f"Testing with: {test_file}\n")
        
    #     # Process single file (dry run first)
    #     processor = AudioraCore(
    #         audio_filepath=test_file,
    #         config_path="configs",
    #         dry_run=True
    #     )
        
    #     context = processor.process()
    #     # print(f"Category: {context.category}")
    #     # print(f"Metadata Date: {context.metadata_date}")
    #     # print(f"Filename Date: {context.filename_date}")
    #     # print(f"Validated Date: {context.validated_date}")
    #     # print(f"Session Name: {context.session_name}")
    #     # print(f"Output Filename: {context.output_filename}")
    #     print(f"\nOutput Path: {context.output_filepath}")
    
    # # Test 2: Batch processing (dry run)
    # print("\n" + "="*60)
    # print("TEST 2: Batch Processing (Dry Run)")
    # print("-" * 40 + "\n")
    
    # nexus = AudioraNexus(
    #     dir_path=test_dir,
    #     config_path="configs",
    #     dry_run=True
    # )
    
    # results = nexus.process_all(progress_bar=True)
    
    # # Summary
    # print("\n" + "="*60)
    # print("RESULTS SUMMARY")
    # print("-" * 40)
    # print(f"Total files processed: {len(results)}")
    # print(f"Successful: {sum(results.values())}")
    # print(f"Failed: {len(results) - sum(results.values())}")
    # print("="*60 + "\n")

    # for result in results:
    #     print(result)
    
    # # Ask user if they want to run for real
    # response = input("Run actual file moves? (yes/no): ").strip().lower()
    # if response == 'yes':
    #     print("\nRunning actual file moves...")
    #     nexus_real = AudioraNexus(
    #         dir_path=test_dir,
    #         config_path="configs",
    #         dry_run=False
    #     )
    #     results_real = nexus_real.process_all(progress_bar=True)
        
    #     print("\n" + "="*60)
    #     print("ACTUAL RUN RESULTS")
    #     print("-" * 40)
    #     print(f"Total files processed: {len(results_real)}")
    #     print(f"Successful: {sum(results_real.values())}")
    #     print(f"Failed: {len(results_real) - sum(results_real.values())}")
    #     print("="*60 + "\n")
    # else:
    #     print("\nSkipped actual file moves.")

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


    audio_source_dir = r"C:\Users\bryan\Downloads\Chuck McGee - Copy"
    audio_target_dir = r"C:\Users\bryan\Downloads\Audio"

    verifier = DirectoryVerifier(audio_source_dir, audio_target_dir)
    # Example 2: Batch processing
    nexus_real = AudioraNexus(
        dir_path=audio_source_dir,
        base_dir=audio_target_dir,
        config_path="configs",
        dry_run=False
    )
    results_real = nexus_real.process_all(progress_bar=True)
    
    success = verifier.report()
    verifier.cleanup()

    #fetch_and_process_emails()

    log_and_display("Finished all tasks.", sticky=True)



if __name__ == "__main__":
    #main()
    #test_pixelporter()
    #test_videosith()
    test_audiora()