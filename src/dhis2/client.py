import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from typing import Dict, Any, Optional

# Setup basic module logger
logger = logging.getLogger(__name__)

class DHIS2Error(Exception):
    """Base exception for DHIS2 Client errors."""
    pass

class DHIS2AuthError(DHIS2Error):
    """Raised on authentication/authorization issues (401, 403)."""
    pass

class DHIS2ConnectionError(DHIS2Error):
    """Raised on timeouts and connection failures."""
    pass

class DHIS2HTTPError(DHIS2Error):
    """Raised on unsuccessful HTTP requests (404, 500, etc.)."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_text: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class DHIS2Client:
    """
    Reusable DHIS2 HTTP client with support for Basic Auth, Personal Access Tokens,
    connection retry, custom timeouts, and safe logging.
    """
    def __init__(
        self,
        base_url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        pat: Optional[str] = None,
        verify_ssl: bool = True,
        timeout: float = 30.0
    ):
        self.base_url = base_url.rstrip('/')
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.session = requests.Session()
        
        if not verify_ssl:
            logger.warning(
                "SSL Verification is disabled for client to %s. "
                "This is not recommended for production environments.",
                self.base_url
            )
            # Disable urllib3 warnings to avoid spamming logs when SSL is disabled
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
        self.session.verify = verify_ssl

        # Configure Authentication
        if pat:
            # DHIS2 uses the "ApiToken" prefix in the Authorization header for PATs
            self.session.headers.update({"Authorization": f"ApiToken {pat}"})
            logger.info("Initialized DHIS2 Client using Personal Access Token (PAT).")
        elif username and password:
            self.session.auth = (username, password)
            logger.info("Initialized DHIS2 Client using Basic Authentication.")
        else:
            logger.warning("Initialized DHIS2 Client without active credentials.")

        # Configure connection retries for temporary failures (429, 502, 503, 504)
        retry_strategy = Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=[429, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Helper method to send requests, handle timeouts, errors, and scrub logs."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        
        # Ensure timeout is always set
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.timeout

        # Scrub sensitive headers if logs are emitted at DEBUG level
        safe_headers = {k: "********" if k.lower() == "authorization" else v for k, v in self.session.headers.items()}
        logger.debug("Request: %s %s with headers %s", method, url, safe_headers)

        try:
            response = self.session.request(method, url, **kwargs)
            logger.debug("Response: %s %s -> Status %d", method, url, response.status_code)
            
            # Check response status
            if response.status_code in (401, 403):
                raise DHIS2AuthError(
                    f"Authentication failed ({response.status_code}) calling {url}. Check your credentials."
                )
            
            response.raise_for_status()
            return response
            
        except requests.exceptions.Timeout as e:
            msg = f"Timeout error connecting to {url} after {kwargs['timeout']} seconds."
            logger.error(msg)
            raise DHIS2ConnectionError(msg) from e
            
        except requests.exceptions.ConnectionError as e:
            msg = f"Connection error connecting to {url}."
            logger.error(msg)
            raise DHIS2ConnectionError(msg) from e
            
        except requests.exceptions.HTTPError as e:
            status_code = response.status_code if 'response' in locals() else None
            text = response.text if 'response' in locals() else ""
            msg = f"HTTP {status_code} error during {method} {url}: {text[:200]}"
            logger.error(msg)
            raise DHIS2HTTPError(msg, status_code=status_code, response_text=text) from e
            
        except DHIS2Error as e:
            # Re-raise DHIS2Error subclasses directly
            raise e
            
        except Exception as e:
            msg = f"Unexpected error during {method} to {url}: {str(e)}"
            logger.error(msg)
            raise DHIS2Error(msg) from e

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, **kwargs) -> requests.Response:
        """Execute HTTP GET request."""
        return self._request("GET", path, params=params, **kwargs)

    def post(self, path: str, json: Optional[Dict[str, Any]] = None, data: Optional[Any] = None, **kwargs) -> requests.Response:
        """Execute HTTP POST request."""
        return self._request("POST", path, json=json, data=data, **kwargs)
