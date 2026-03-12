import os
import random
import subprocess
import re
import logging
import argparse
import shutil
import importlib.util

from time import sleep
from typing import List, Optional, Tuple, Union
from logging.handlers import RotatingFileHandler


# Logging setup

LOG_PATH = os.path.join(os.path.expanduser('~'), ".config", "printer-simulation")
os.makedirs(LOG_PATH, exist_ok=True)

format_str = "%(asctime)s [PID %(process)d] - %(funcName)s - %(levelname)s - %(message)s"
class LevelBasedFormatter(logging.Formatter):
    """Custom formatter to change format based on log level."""
    def format(self, record):
        if record.levelno == logging.INFO:
            fmt = "%(message)s"
        else:
            fmt = "%(levelname)s - %(message)s"
        formatter = logging.Formatter(fmt)
        return formatter.format(record)


formatter = logging.Formatter(format_str)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
logger.addHandler(console_handler)

file_handler = RotatingFileHandler(
    os.path.join(os.path.expanduser(LOG_PATH), 'printer-simulation.log'),
    maxBytes=1024*1024, 
    backupCount=3
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


# Dependencies and DISPLAY check

def _check_binary(name: str) -> bool:
    """Check if a binary is installed."""
    res = subprocess.run(['which', name], capture_output=True, text=True)
    return res.returncode == 0


def _check_python_dependency(name: str) -> bool:
    """Check if a Python dependency is installed."""
    return importlib.util.find_spec(name) is not None


def _check_and_import_dependencies():
    """Check if all dependencies are installed and import them."""
    logger.debug("Checking dependencies...")
    try:
        # Check if DISPLAY variable is set
        logger.debug("Checking DISPLAY environment variable...")
        if 'DISPLAY' not in os.environ:
            raise EnvironmentError("DISPLAY environment variable is not set. Please run this script in a graphical environment.")

        # Check if dependencies are installed
        logger.debug("Checking required binaries and Python packages...")
        binaries = ['firefox', 'eog', 'libreoffice', 'gedit', 'wmctrl', 'input-simulation']
        python_modules = ['filelock']

        bins_not_installed = []
        python_not_installed = []
        for bin in binaries:
            if not _check_binary(bin):
                bins_not_installed.append(bin)
        for py_mod in python_modules:
            if not _check_python_dependency(py_mod):
                python_not_installed.append(py_mod)
        
        if bins_not_installed or python_not_installed:
            error_msg = f"""
Some dependencies are not installed.
Binaries not installed: {bins_not_installed}.
Python packages not installed: {python_not_installed}.
Please install them and try again."""
            raise ModuleNotFoundError(error_msg)
            # raise ModuleNotFoundError(f"Dependencies not installed: {', '.join(not_installed)}. Please install them and try again.")

        # Everything is fine, import the dependencies
        logger.debug("All dependencies are installed.")

        global FileLock
        from filelock import FileLock

        # for mod in python_modules:
        #     globals()[mod] = importlib.import_module(mod)

        logger.debug("All dependencies imported.")
    except Exception as e:
        # Log the error to a separate error log file with traceback and environment variables
        import traceback
        import datetime

        error_file = os.path.join(LOG_PATH, "error_printer-simulation.log")
        logger.error(f"Dependency check failed: {e}")
        logger.error(f"Check the error log {error_file} for more details.")

        with open(error_file, "w") as file:
            file.write("Date and time: \n")
            file.write(str(datetime.datetime.now()))
            file.write("\n\n")
            file.write("Error: \n")
            file.write(str(e))
            file.write("\n\n")
            file.write("Traceback: \n")
            file.write(str(traceback.format_exc()))
            file.write("\n\n")
            file.write("Environment variables: \n")
            file.write(str(os.environ))
            file.write("\n\n")
        exit(1)


# Lock setup

def _setup_locks():
    global LOCK, LOCK_INPUT
    LOCK = FileLock(os.path.join("/", "opt", "scripts", ".printer.lock"))
    LOCK_INPUT = FileLock(os.path.join("/", "opt", "scripts", ".input.lock"))


# Input simulation functions

def _set_env():
    """Set the INPUT_LOCK_HELD environment variable for subprocesses."""
    env = os.environ.copy()
    env['INPUT_LOCK_HELD'] = '1'  # Hint to input-simulation that the lock is already held
    return env


def input_simulation(sequence: List[str], verb: str, args: Optional[dict] = None, debug: bool = False):
    """Simulate a sequence of inputs using input-simulation."""
    env = _set_env()

    # Convert args dict to a list of command line arguments
    args_l = [f"{key}={value}" if value else f"{key}" for key, value in args.items()] if args is not None else []
    if debug:
        args_l.append('--debug')
    sequence_string = ' '.join(sequence)

    if args_l:
        command = ['input-simulation', verb] + args_l + [f"{sequence_string}"]
    else:
        command = ['input-simulation', verb, f"{sequence_string}"]
    logger.debug(f"Invoking input-simulation command with verb '{verb}', args: {args_l} and sequence (truncated at 50): {sequence_string[:50]}...")
    subprocess.run(command, env=env)
    logger.debug("Returned from input-simulation.")


def input_key(key: str, presses: int = 1, args: Optional[dict] = None, debug: bool = False):
    """Simulate a key press using input-simulation."""
    sequence = [f'K,{key},{presses}']
    input_simulation(sequence, 'keyboard', args, debug)


def input_type(text: str, args: Optional[dict] = None, debug: bool = False):
    """Simulate typing text using input-simulation."""
    sequence = [f'T,"{text}"']
    input_simulation(sequence, 'keyboard', args, debug)


def input_keyboard_sequence(sequence: List[str], args: Optional[dict] = None, debug: bool = False):
    """Simulate a sequence of keyboard actions using input-simulation."""
    input_simulation(sequence, 'keyboard', args, debug)


def input_sequence(sequence: List[str], args: Optional[dict] = None, debug: bool = False):
    """Simulate a sequence of input actions using input-simulation."""
    input_simulation(sequence, 'input', args, debug)


# Auxiliary functions

def get_system():
    if os.name == 'nt':
        return 'Windows'
    else:
        return 'Linux'
    

def wait_for_program(program: str):
    logger.debug(f"Waiting for {program} to load.")
    while True:
        result = subprocess.run(['wmctrl', '-l'], capture_output=True, text=True)
        if program in result.stdout:
            logger.debug(f"{program} is loaded.")
            break
        sleep(1)  # Wait for 1 second before checking again
    sleep(2)  # Fail-safe sleep to ensure the program is fully loaded


def sleep_action(delay: Union[float, Tuple[float, float]], extra_delay: float = 0.0):
    if isinstance(delay, tuple):
        min_delay, max_delay = delay
        delay = random.uniform(min_delay, max_delay)
    logger.debug(f"Sleeping for {delay} seconds (extra {extra_delay} seconds).")
    sleep(delay + extra_delay)


def process_output(file: str, output: Optional[str] = None, is_libreoffice: bool = False) -> str:
    if output:
        output = os.path.expanduser(output)
        if os.path.isdir(output):
            logger.debug("Output is a directory, using the same filename as the input file.")
            output_file = os.path.join(output, os.path.basename(file) + '.pdf')
        else:
            logger.debug("Output is a filename.")
            # If the output is a plain filename, output_file should be in the same directory as the input file
            # If not, it will be the output filename
            if os.path.isdir(os.path.dirname(output)):
                output_file = output
            else:
                output_file = os.path.join(os.path.dirname(file), output)
        
        if not is_libreoffice:
            # Move the file to the output directory
            logger.debug(f"Moving the file to {output_file}.")
            shutil.move(f"{file}.pdf", output_file)
    else:
        logger.debug("No output directory provided, using the same directory as the input file.")
        output_file = file + '.pdf'
    
    return output_file


# Windows printing functions (not implemented yet)

def print_in_windows(
        visible: bool, 
        files: List[str],
        min_delay: float,
        max_delay: float,
        delay: float,
        output: Optional[str]
    ):
    pass


# Linux printing functions


def start_print_process_visually(
        file: str, 
        output: Optional[str], 
        delay: Union[float, Tuple[float, float]], 
        is_libreoffice: bool = False,
        is_firefox: bool = False,
        debug: bool = False
    ) -> str:
    # Start the print dialog
    logger.debug(f"Starting the print dialog for {file}.")
    sleep(2)
    input_key('Ctrl+P', debug=debug)
    sleep(3)

    # Go to the printers list
    logger.debug("Selecting the printer.")
    args = {
        "--press-interval": 0.5,
        "--typing-interval": 0.2,
        "--sleep": 1.0
    }
    if is_libreoffice:
        sequence = [
            'K,Shift+Tab,5',  # Go to the print option
            'K,Space',  # Select the print option
            'T,"imprimir"',  # Change the printer to print to a file
            'S,0.0',
            'K,Enter,2'  # Select the printer
        ]
    elif is_firefox:
        sequence = [
            'K,Tab,5',  # Go to the print option
            'K,Enter',  # Select the print option
            'K,Tab',  # Go to the list of printers
            'T,"imprimir"',  # Change the printer to print to a file
            'S,0.0',
            'K,Tab,2',  # Select the filename field,
            'S,0.0',
            'K,Enter'  # Press Enter to write the filename
        ]
    else:
        sequence = [
            'K,Tab,1',  # Go to the printer text field
            'T,"imprimir"',  # Write "imprimir" to ensure the right printer is selected
            'S,0.0',
            'K,Tab,2',  # Go to the filename field
            'K,Enter'  # Press Enter to write the filename
        ]
    input_keyboard_sequence(sequence, args, debug)
        
    # Write the filename
    # Check the output (is it a directory or a filename?)
    output_file = process_output(file, output, is_libreoffice)

    sequence = [
        'K,Ctrl+A',  # Select all text
        'S,0.0',
        f'T,"{output_file}"',  # Type the filename
        'S,1.0',
        'K,Enter',  # Select the filename
        'S,1.0',
    ]
    input_keyboard_sequence(sequence, args, debug)

    if is_libreoffice:
        # These are needed in case of confirmation dialog on an existing file
        proc = subprocess.run(['wmctrl', '-lx'], capture_output=True, text=True)
        save_windows_before = [line for line in proc.stdout.splitlines() if 'soffice.Soffice' in line]
        sequence = [
            'K,Tab',
            'K,Enter',
            # 'K,Ctrl+Z,2'  # Needed to undo in case of printing a text file
        ]
        proc = subprocess.run(['wmctrl', '-lx'], capture_output=True, text=True)
        save_windows_after = [line for line in proc.stdout.splitlines() if 'soffice.Soffice' in line]
        if len(save_windows_after) > len(save_windows_before):
            logger.debug("Confirmation dialog detected, confirming overwrite.")
            sequence = [
                'K,Tab',
                'K,Enter'
            ]
            input_keyboard_sequence(sequence, args, debug)
    if not is_libreoffice:
        sequence = [
            'K,Shift+Tab,3',  # Go to the "Print" button
            'K,Enter,2',  # Two presses in case of confirmation dialog of an existing file
            'K,Ctrl+Z'  # Needed to undo in case of printing a text file
        ]
    input_keyboard_sequence(sequence, args, debug)
    sleep(1)

    return output_file



def print_image_linux(file: str, output: Optional[str], delay: Union[float, Tuple[float, float]]):
    dir_path = os.path.dirname(os.path.abspath(os.path.expanduser(file)))
    logger.info(f"Dir path: {dir_path}")
    subprocess.Popen(["eog", file], cwd=dir_path)
    logger.info(f"Priting image {file}...")
    # In case of eog, the program name is the name of the file (just the last part)
    wait_for_program(os.path.basename(file))

    output_file = start_print_process_visually(file, output, delay)

    return output_file


def print_text_linux(file: str, output: Optional[str], delay: Union[float, Tuple[float, float]]):
    subprocess.Popen(["gedit", file])
    logger.info(f"Priting text file {file}...")
    wait_for_program("gedit")

    output_file = start_print_process_visually(file, output, delay)

    return output_file


def print_libreoffice_linux(file: str, output: Optional[str], delay: Union[float, Tuple[float, float]]):
    subprocess.Popen(["libreoffice", file])
    logger.info(f"Priting LibreOffice file {file}...")
    wait_for_program("LibreOffice")

    output_file = start_print_process_visually(file, output, delay, is_libreoffice=True)

    return output_file


def print_pdf_linux(file: str, output: Optional[str], delay: Union[float, Tuple[float, float]]):
    subprocess.Popen(["firefox", "--new-window", file])
    logger.info(f"Priting PDF {file}...")
    basename = os.path.basename(file)
    wait_for_program(f"{basename} — Mozilla Firefox")

    output_file = start_print_process_visually(file, output, delay, is_firefox=True)

    return output_file


def open_pdf_linux(file: str, delay: Union[float, Tuple[float, float]], debug: bool = False):
    logger.info(f"Opening generated PDF {file}.")
    # subprocess.Popen(["evince", file])  # FIXME: This is not working
    subprocess.Popen(["firefox", "--new-window", file])
    window_name = f"{file} — Mozilla Firefox".split("/")[-1]  # Get the last part of the path
    wait_for_program(window_name)
    logger.info(f"Simulating reading the PDF...")
    sleep_action(delay)  # TODO: add actions such as zooming, scrolling, etc.

    # Ensure the focus is on the evince window
    # os.system("wmctrl -xa evince.Evince")

    # Execute wmctrl -l and get the window list
    res = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True)
    lines = res.stdout.splitlines()

    # Busca la ventana que contenga el nombre especificado
    for line in lines:
        if window_name in line:
            wid = line.split()[0]  # Get the window ID
            # Cambia el foco a la ventana
            subprocess.run(["wmctrl", "-ia", wid])
            logger.debug(f"Changing focus to {window_name}.")
            break
    sleep(1)

    # Close the evince/firefox window
    input_key('Alt+F4', debug=debug)
    sleep(1)


def print_visually_linux(
        files: List[str],
        min_delay: float,
        max_delay: float,
        delay: float,
        output: Optional[str],
        debug: bool = False
    ):
    for file in files:
        file = os.path.abspath(os.path.expanduser(file))

        # Get the program based on the MIME type of the file
        mime_type = subprocess.run(['xdg-mime', 'query', 'filetype', file], capture_output=True, text=True).stdout.strip()
        program = subprocess.run(['xdg-mime', 'query', 'default', mime_type], capture_output=True, text=True).stdout.strip()
        logger.debug(f"File {file} has MIME type {mime_type} and default program {program}.")
    
        # Check if the file is an image
        if "eog" in program or mime_type.startswith('image/'):
            output_file = print_image_linux(file, output, 0.125)
        # Check if the file is a LibreOffice file
        elif "libreoffice" in program or mime_type in ['application/vnd.oasis.opendocument.text', 'application/vnd.oasis.opendocument.spreadsheet', 'application/vnd.oasis.opendocument.presentation', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.openxmlformats-officedocument.presentationml.presentation']:
            logger.info(f"Printing LibreOffice file {file}")
            output_file = print_libreoffice_linux(file, output, 0.125)
        # Check if the file is a PDF
        elif "evince" in program or mime_type == 'application/pdf':
            logger.info(f"Printing PDF file {file}")
            output_file = print_pdf_linux(file, output, 0.125)
        # Check if the file a text file
        else:
            logger.info(f"Printing text file {file}")
            output_file = print_text_linux(file, output, 0.125)
        # else:
        #     output_file = ""

        open_pdf_linux(output_file, (min_delay, max_delay))
        # os.system("wmctrl -xa gedit.Gedit")
        # sleep(1)
        input_key('Alt+F4', debug=debug)  # Close gedit
        sleep(1)



def print_in_linux(
        visible: bool, 
        files: List[str],
        min_delay: float,
        max_delay: float,
        delay: float,
        output: Optional[str]
    ):
    if visible:
        logger.debug(f"Trying to acquire input lock on {LOCK_INPUT.lock_file}.")
        with LOCK_INPUT.acquire():
            logger.debug(f"Trying to acquire lock on {LOCK.lock_file}.")
            with LOCK.acquire():
                print_visually_linux(files, min_delay, max_delay, delay, output)
    else:
        pass


def init():
    _check_and_import_dependencies()
    _setup_locks()


def main():
    parser = argparse.ArgumentParser(
        prog='printer-simulation',
        description='Simulate activity printing diffent types of files, such as text files, images, etc.',
    )

    # Make a visible and invisible arguments, they are mutually exclusive
    parser.add_argument('files', type=str, help='Files to print.', nargs='+')
    parser.add_argument('--visible', action='store_true', help='Prints visually (using the GUI)', default=True)
    parser.add_argument('--invisible', action='store_false', dest="visible", help='Prints through commands')
    parser.add_argument('--output', '-O', type=str, required=False, help='Output directory to save files to. If not a directory, it will be used as a filename. If not provided, the directory where the input files are will be used.')
    parser.add_argument('--min-delay', type=float, default=5.0, help='Minimum delay between actions (in seconds).')
    parser.add_argument('--max-delay', type=float, default=10.0, help='Maximum delay between actions (in seconds).')
    parser.add_argument('--delay', type=float, default=None, help='Fixed delay between actions (in seconds). Overrides --min-delay and --max-delay.')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode.')

    # Parse arguments
    args, unknown = parser.parse_known_args()

    if args.debug:
        console_handler.setFormatter(formatter)
    else:
        console_handler.setFormatter(LevelBasedFormatter())
        console_handler.setLevel(logging.INFO)

    logger.info("Starting printer-simulation.")
    if unknown:
        logger.warning(f"Unknown arguments ignored: {unknown}")

    init()

    logger.debug(f"Printing will be {'visible' if args.visible else 'invisible'}.")

    # Check the OS
    if get_system() == 'Windows':
        logger.debug("Running in Windows.")
        print_in_windows(args.visible, args.files, args.min_delay, args.max_delay, args.delay, args.output)
    else:
        logger.debug("Running in Linux.")
        print_in_linux(args.visible, args.files, args.min_delay, args.max_delay, args.delay, args.output)


if __name__ == '__main__':
    main()
else:
    init()
