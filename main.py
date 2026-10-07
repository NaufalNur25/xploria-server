import asyncio
import logging
import os
import sys

# Tambahkan src ke system path agar import hal berfungsi
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from ws_server import start_server
from hal.core import cleanup_gpio

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    exit_code = 0
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        logging.info("Daemon Server stopped manually.")
    except Exception:
        # Log traceback lengkap dan keluar dengan kode non-zero agar
        # systemd (Restart=on-failure) me-restart daemon secara otomatis.
        logging.exception("Server crashed")
        exit_code = 1
    finally:
        cleanup_gpio()

    sys.exit(exit_code)
