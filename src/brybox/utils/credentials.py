import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class EmailCredentials:
    """Email account credentials and connection settings."""

    email: str
    password: str
    imap_server: str
    imap_port: int = 993

    def __post_init__(self):
        if not self.email or not self.password:
            raise ValueError('Email and password are required')
        if not self.imap_server:
            raise ValueError('IMAP server is required')


@dataclass
class WebCredentials:
    """Credentials for web automation services."""

    # NOTE Consider: Refactor to dynamic credential discovery (dict-based with
    # env pattern parsing) if service count grows beyond ~20-50. Current hardcoded
    # approach chosen for explicitness and type safety. Interface will remain compatible.
    techem_user: str | None = None
    techem_password: str | None = None
    kfw_user: str | None = None
    kfw_password: str | None = None


class CredentialsManager:
    """Manages loading credentials from environment variables."""

    def __init__(self, env_file: str | None = None):
        """Load environment variables from file."""
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()  # Load from default .env file

    def get_email_credentials(self) -> EmailCredentials:
        """Load email credentials from environment."""
        email = os.getenv('EMAIL')
        password = os.getenv('APP_PWD')
        imap_server = os.getenv('IMAP_SERVER', 'imap.gmail.com')  # Default to Gmail
        imap_port = int(os.getenv('IMAP_PORT', '993'))

        return EmailCredentials(email=email, password=password, imap_server=imap_server, imap_port=imap_port)

    def get_web_credentials(self) -> WebCredentials:
        """Load web automation credentials from environment."""
        return WebCredentials(
            techem_user=os.getenv('USER_MAIN'),
            techem_password=os.getenv('TECHEM_PWD'),
            kfw_user=os.getenv('USER_KFW'),
            kfw_password=os.getenv('KFW_PWD'),
        )
