import logging
import time
import xmlrpc.client

logger = logging.getLogger(__name__)

RECEIVE_PUNCHES_MODEL = 'biometric.config'
RECEIVE_PUNCHES_METHOD = 'action_receive_punches'


class OdooRPCError(Exception):
    pass


class OdooClient:

    def __init__(self, url, db, login, api_key=None, password=None,
                 max_retries=3, retry_delay=2, timeout=30):
        self.url = url.rstrip('/')
        self.db = db
        self.login = login
        self.api_key = api_key
        self.password = password
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        self._uid = None
        self._common = xmlrpc.client.ServerProxy('%s/xmlrpc/2/common' % self.url, allow_none=True)
        self._models = xmlrpc.client.ServerProxy('%s/xmlrpc/2/object' % self.url, allow_none=True)

    @property
    def auth_password(self):
        return self.api_key or self.password

    def authenticate(self):
        logger.info("Authenticating with Odoo at %s (db=%s, user=%s)", self.url, self.db, self.login)
        try:
            uid = self._common.authenticate(self.db, self.login, self.auth_password, {'interactive': False})
        except Exception as error:
            raise OdooRPCError("XML-RPC authentication failed: %s" % error)
        if not uid:
            raise OdooRPCError("Authentication rejected, check login (%s) and API key" % self.login)
        self._uid = uid
        logger.info("Authenticated as uid=%s", uid)
        return uid

    def call(self, model, method, args=None, kwargs=None):
        if not self._uid:
            self.authenticate()
        args = args or []
        kwargs = kwargs or {}
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._models.execute_kw(self.db, self._uid, self.auth_password,
                                               model, method, args, kwargs)
            except xmlrpc.client.Fault as fault:
                message = fault.faultString or ''
                if 'Session expired' in message or 'Access Denied' in message:
                    logger.warning("Re-authenticating after auth fault: %s", message)
                    self._uid = None
                    self.authenticate()
                    if attempt < self.max_retries:
                        continue
                raise OdooRPCError("XML-RPC fault: %s" % message)
            except (ConnectionError, TimeoutError, OSError) as error:
                logger.warning("Odoo RPC attempt %s/%s failed: %s", attempt, self.max_retries, error)
                if attempt >= self.max_retries:
                    raise
                time.sleep(self.retry_delay * attempt)

    def send_punches(self, serial_number, punches):
        return self.call(RECEIVE_PUNCHES_MODEL, RECEIVE_PUNCHES_METHOD,
                         kwargs={'serial_number': serial_number, 'punches': punches})
