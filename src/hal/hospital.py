import logging

logger = logging.getLogger(__name__)

class HospitalHAL:
    def __init__(self):
        pass

    def open_jitsi(self, roomName: str, displayName: str, role: str, subject: str = ""):
        """
        Mengirim instruksi via WebSocket (Telemetry) agar Flutter membuka layar Jitsi.
        """
        from hal import telemetry
        logger.info(f"Hospital Jitsi: Membuka room '{roomName}' sebagai {role}")
        
        telemetry.send(
            action="open_jitsi",
            roomName=roomName,
            displayName=displayName,
            role=role,
            subject=subject
        )

    def close_jitsi(self):
        """
        Mengirim instruksi via WebSocket agar Flutter menutup layar Jitsi.
        """
        from hal import telemetry
        logger.info("Hospital Jitsi: Menutup room")
        telemetry.send(
            action="close_jitsi"
        )
