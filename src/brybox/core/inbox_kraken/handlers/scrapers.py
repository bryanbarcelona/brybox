from brybox.core.models.email import ProcessingContext, ProcessResult
from brybox.core.web_marionette.gothaer import GothaerScraper
from brybox.core.web_marionette.kfw import KfwScraper
from brybox.core.web_marionette.techem import TechemScraper
from brybox.exceptions.emails import (
    InboxKrakenConfigurationError,
    InboxKrakenOperationFailedError,
)
from brybox.exceptions.scrapers import (
    ScraperAuthenticationError,
    ScraperConfigurationError,
    ScraperDownloadError,
    ScraperError,
    ScraperNavigationError,
)
from brybox.utils.credentials import WebCredentials


def gothaer_handler(ctx: ProcessingContext) -> ProcessResult:
    creds: WebCredentials | None = ctx.creds
    if creds is None:
        raise InboxKrakenConfigurationError('Missing credentials object', config_key='credentials')

    gothaer_user = creds.gothaer_user
    gothaer_password = creds.gothaer_password

    if not isinstance(gothaer_user, str) or not gothaer_user:
        raise InboxKrakenConfigurationError('Missing or invalid Gothaer username', config_key='gothaer_username')

    if not isinstance(gothaer_password, str) or not gothaer_password:
        raise InboxKrakenConfigurationError('Missing or invalid Gothaer password', config_key='gothaer_password')

    try:
        scraper = GothaerScraper(
            username=gothaer_user, password=gothaer_password, download_dir=str(ctx.save_dir), headless=False
        )
        result = scraper.download()

        if not result or result.downloaded == 0:
            raise InboxKrakenOperationFailedError('Gothaer scraper finished but no files were downloaded.')

        return ProcessResult(
            success=result.success,
            target_path=None,
            is_healthy=True,
            error_message='; '.join(result.errors) if result.errors else '',
            can_delete=result.success,
        )

    except ScraperAuthenticationError as e:
        raise InboxKrakenOperationFailedError(f'Gothaer authentication failed: {e}', error_detail=str(e)) from e

    except ScraperNavigationError as e:
        raise InboxKrakenOperationFailedError(f'Gothaer site structure error: {e}', error_detail=str(e)) from e

    except ScraperError as e:
        raise InboxKrakenOperationFailedError(f'Gothaer scraper failed: {e}', error_detail=str(e)) from e


def kfw_handler(ctx: ProcessingContext) -> ProcessResult:
    creds: WebCredentials | None = ctx.creds
    if creds is None:
        raise InboxKrakenConfigurationError('Missing credentials object', config_key='credentials')

    kfw_user = creds.kfw_user
    kfw_password = creds.kfw_password

    if not isinstance(kfw_user, str) or not kfw_user:
        raise InboxKrakenConfigurationError('Missing or invalid KfW username', config_key='kfw_username')

    if not isinstance(kfw_password, str) or not kfw_password:
        raise InboxKrakenConfigurationError('Missing or invalid KfW password', config_key='kfw_password')

    try:
        scraper = KfwScraper(username=kfw_user, password=kfw_password, download_dir=str(ctx.save_dir), headless=True)
        result = scraper.download()

        if not result or result.downloaded == 0:
            raise InboxKrakenOperationFailedError('KfW Scraper finished but no files were downloaded.')

        return ProcessResult(
            success=result.success,
            target_path=None,
            is_healthy=True,
            error_message='; '.join(result.errors) if result.errors else '',
            can_delete=result.success,
        )

    except ScraperAuthenticationError as e:
        raise InboxKrakenOperationFailedError(f'KfW authentication failed: {e}', error_detail=str(e)) from e

    except ScraperNavigationError as e:
        raise InboxKrakenOperationFailedError(f'KfW site structure error: {e}', error_detail=str(e)) from e

    except ScraperConfigurationError as e:
        raise InboxKrakenConfigurationError(f'KfW scraper configuration: {e}', config_key='scraper_setup') from e

    except ScraperError as e:
        raise InboxKrakenOperationFailedError(f'KfW scraper failed: {e}', error_detail=str(e)) from e


def techem_handler(ctx: ProcessingContext) -> ProcessResult:
    creds: WebCredentials | None = ctx.creds
    if creds is None:
        raise InboxKrakenOperationFailedError('Missing credentials object')

    # Validate Techem credentials are strings
    techem_user = creds.techem_user
    techem_password = creds.techem_password

    if not isinstance(techem_user, str) or not techem_user:
        raise InboxKrakenOperationFailedError('Missing or invalid Techem username')

    if not isinstance(techem_password, str) or not techem_password:
        raise InboxKrakenOperationFailedError('Missing or invalid Techem password')

    try:
        scraper = TechemScraper(
            username=techem_user, password=techem_password, download_dir=str(ctx.save_dir), headless=False
        )
        result = scraper.download()

        if not result or result.errors:
            raise InboxKrakenOperationFailedError(
                f'Techem Scraper finished with errors: {result.errors if result else "No result"}'
            )

        return ProcessResult(
            success=result.success,
            target_path=None,
            is_healthy=True,
            error_message='; '.join(result.errors) if result.errors else '',
            can_delete=result.success,
        )

    except ScraperAuthenticationError as e:
        raise InboxKrakenOperationFailedError(f'Techem authentication failed: {e}', error_detail=str(e)) from e

    except ScraperNavigationError as e:
        raise InboxKrakenOperationFailedError(f'Techem site error: {e}', error_detail=str(e)) from e

    except ScraperDownloadError as e:
        raise InboxKrakenOperationFailedError(f'Techem download failed: {e}', error_detail=str(e)) from e

    except ScraperError as e:
        raise InboxKrakenOperationFailedError(f'Techem scraper failed: {e}', error_detail=str(e)) from e
