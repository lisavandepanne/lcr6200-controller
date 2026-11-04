from pipython import GCSDevice

# ============ USER SETTINGS ============

CONNECTION = "usb"
USB_SERIAL_NUMBER = None
SERIAL_PORT = "COM3"
BAUDRATE = 115200
CONTROLLER_MODEL = "C-863"

# ======================================
with GCSDevice('C-884') as pidevice:
    pidevice.InterfaceSetupDlg()
    print(pidevice.qIDN())
pidevice.CloseConnection()