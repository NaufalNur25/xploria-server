class RFIDHAL:
    def __init__(self):
        self._pn532 = None
        self._initialized = False
        self._cards = {}

    def _init_device(self):
        if not self._initialized:
            self._initialized = True
            try:
                import board
                import busio
                from adafruit_pn532.i2c import PN532_I2C

                i2c = busio.I2C(board.SCL, board.SDA)
                self._pn532 = PN532_I2C(i2c, debug=False)
                self._pn532.SAM_configuration()
            except Exception:
                self._pn532 = None

    def read_uid(self, timeout=0.1):
        self._init_device()
        if not self._pn532:
            return None
        try:
            uid = self._pn532.read_passive_target(timeout=timeout)
            if uid is not None:
                return ':'.join([f'{x:02X}' for x in uid])
            return None
        except Exception:
            return None

    def _normalize_uid(self, uid: str) -> str:
        if not uid:
            return ""
        return str(uid).replace(":", "").replace("-", "").replace(" ", "").strip().upper()

    def register_card(self, uid: str, access_type: str = "ALLOW"):
        clean_uid = self._normalize_uid(uid)
        if not clean_uid:
            return
        self._cards[clean_uid] = access_type.upper()

    def unregister_card(self, uid: str):
        clean_uid = self._normalize_uid(uid)
        if not clean_uid:
            return
        self._cards.pop(clean_uid, None)

    def check_status(self, uid: str = None) -> str:
        target_uid = uid if uid else self.read_uid()
        clean_uid = self._normalize_uid(target_uid)
        if not clean_uid:
            return "TIDAK_TERDAFTAR"
        status = self._cards.get(clean_uid)
        if status == "ALLOW":
            return "DIIZINKAN"
        elif status == "DENY":
            return "DITOLAK"
        return "TIDAK_TERDAFTAR"

    def is_allowed(self, uid: str = None) -> bool:
        return self.check_status(uid) == "DIIZINKAN"
