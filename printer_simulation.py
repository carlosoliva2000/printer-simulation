import os
import random
import subprocess
import time
import re
import logging
import argparse
import shutil
import importlib.util

from time import sleep
from pathlib import Path
from typing import List, Optional, Tuple, Union
from logging.handlers import RotatingFileHandler


# Globals

FILE_PROGRAM_PROC = None
PRINT_PROGRAM_PROC = None
CONTENTION_THRESHOLD = 0.5  # Seconds to consider that there is contention on the lock (i.e., that it was not acquired immediately)


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

def _get_active_x11_session():
    """
    Returns (user, uid, runtime_path) if an active X11 session exists.
    Otherwise returns (None, None, None).
    """
    result = subprocess.run(
        ["loginctl", "--no-legend", "list-sessions"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        return None, None, None

    for line in result.stdout.splitlines():
        if not line.strip():
            continue

        parts = line.split()
        if len(parts) < 3:
            continue

        session, uid, user = parts[:3]

        info = subprocess.run(
            ["loginctl", "show-session", session],
            capture_output=True,
            text=True
        )

        data = {}
        for l in info.stdout.splitlines():
            if "=" in l:
                k, v = l.split("=", 1)
                data[k] = v

        if data.get("Active") == "yes" and data.get("Type") == "x11":

            runtime_info = subprocess.run(
                ["loginctl", "show-user", user, "-p", "RuntimePath"],
                capture_output=True,
                text=True
            )

            runtime_path = None
            if runtime_info.returncode == 0:
                line = runtime_info.stdout.strip()
                if "=" in line:
                    runtime_path = line.split("=", 1)[1]

            return user, uid, runtime_path

    return None, None, None


def _ensure_graphical_session(timeout=120):
    logger.info("Ensuring graphical session is ready...")

    start = time.perf_counter()

    while time.perf_counter() - start < timeout:
        user, uid, runtime_path = _get_active_x11_session()

        if not user:
            logger.debug("No active X11 session yet...")
            time.sleep(1)
            continue

        if not runtime_path:
            logger.debug("RuntimePath not available yet...")
            time.sleep(1)
            continue

        xauthority = os.path.join(runtime_path, "gdm", "Xauthority")

        if not os.path.exists(xauthority):
            logger.debug(f"Xauthority not found at {xauthority}")
            time.sleep(1)
            continue

        env = os.environ.copy()
        env["DISPLAY"] = ":0"
        env["XAUTHORITY"] = xauthority

        result = subprocess.run(
            ["xdpyinfo"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        if result.returncode == 0:
            logger.info(f"Graphical session ready for user {user}.")
            os.environ["DISPLAY"] = ":0"
            os.environ["XAUTHORITY"] = xauthority
            logger.info("Waiting an additional 1 second to ensure the session is fully ready...")
            time.sleep(1)
            return

        logger.debug("X server not accepting connections yet...")
        time.sleep(1)

    logger.error("Timeout waiting for graphical session.")
    exit(1)


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
    LOCK = FileLock(os.path.join("/", "opt", "locks", ".printer.lock"))
    LOCK_INPUT = FileLock(os.path.join("/", "opt", "locks", ".input.lock"))


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

def proc_to_str(proc: subprocess.Popen) -> str:
    """Convert a subprocess.Popen object to a string for logging."""
    if isinstance(proc.args, list):
        cmd = ' '.join(proc.args)
    else:
        cmd = str(proc.args)
    return cmd


def close_failsafe(proc: subprocess.Popen):
    """Failsafe to close a proc if something goes wrong."""
    sleep(2)
    proc_name = f"'{proc_to_str(proc)}'"
    if proc.poll() is None:  # If the process is still running
        logger.debug(f"{proc_name} process (PID: {proc.pid}) is still running, terminating it (SIGTERM).")
        proc.terminate()
        
        try:
            proc.wait(timeout=5)  # Wait for the process to terminate gracefully
            logger.debug(f"{proc_name} process terminated gracefully.")
        except subprocess.TimeoutExpired:
            logger.debug(f"{proc_name} process did not terminate, killing it (SIGKILL).")
            proc.kill()
            proc.wait()


def get_system():
    if os.name == 'nt':
        return 'Windows'
    else:
        return 'Linux'
    

def wait_for_program(program: str, pid: Optional[int] = None):
    logger.debug(f"Waiting for {program} to load.")
    while True:
        result = subprocess.run(['wmctrl', '-l'], capture_output=True, text=True)
        if program in result.stdout:
            logger.debug(f"{program} (PID: {pid}) is loaded.")
            break
        sleep(1)  # Wait for 1 second before checking again
    sleep(2)  # Fail-safe sleep to ensure the program is fully loaded


def sleep_action(delay: Union[float, Tuple[float, float]], extra_delay: float = 0.0):
    if isinstance(delay, tuple):
        min_delay, max_delay = delay
        delay = random.uniform(min_delay, max_delay)
    logger.debug(f"Sleeping for {delay} seconds (extra {extra_delay} seconds).")
    sleep(delay + extra_delay)


def process_output(file: str, output: Optional[str] = None) -> str:
    if output:
        aux_output = os.path.abspath(os.path.expanduser(output))
        logger.debug(f"Output provided: {aux_output}")
        if os.path.isdir(aux_output):
            logger.debug("Output is a directory, using the same filename as the input file.")
            output_file = os.path.join(aux_output, os.path.basename(file) + '.pdf')
        else:
            logger.debug("Output is a filename.")
            # If the output is a plain filename, output_file should be in the same directory as the input file
            # If not, it will be the output filename

            # Check if output is just a filename (no directory part)
            if not os.path.dirname(output):
                logger.debug("Output is a plain filename, using the same directory as the input file.")
                output_file = os.path.join(os.path.dirname(file), output)
            
            # Check if the directory part of the output is a valid directory
            elif os.path.isdir(os.path.dirname(aux_output)):
                logger.debug("Output is a filename with a valid directory.")
                output_file = aux_output
            else:
                logger.error("Output must be a valid directory or filename.")
                raise ValueError("Output must be a valid directory or filename.")
    else:
        logger.debug("No output directory provided, using the same directory as the input file.")
        output_file = file + '.pdf'
    
    return output_file


def get_random_file_from_dir(dir: str) -> Optional[str]:
    logger.info(f"Getting a random file from directory {dir}.")
    files = [f for f in os.listdir(dir) if not os.path.isdir(f)]
    if not files:
        logger.info(f"No files found in {dir}.")
        return None
    
    random_file = os.path.abspath(
        os.path.join(
            dir, 
            random.choice(files)
        )
    )
    logger.info(f"Random file chosen: {random_file}.")
    
    return os.path.join(dir, random_file)


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
    output_file = process_output(file, output)

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



def print_image_linux(file: str, output: Optional[str], debug: bool = False):
    dir_path = os.path.dirname(os.path.abspath(os.path.expanduser(file)))
    
    global FILE_PROGRAM_PROC
    FILE_PROGRAM_PROC = subprocess.Popen(["eog", file], cwd=dir_path)
    logger.info(f"Priting image {file}...")
    # In case of eog, the program name is the name of the file (just the last part)
    program_name = os.path.basename(file)
    wait_for_program(program_name, pid=FILE_PROGRAM_PROC.pid)

    output_file = start_print_process_visually(file, output, debug=debug)

    return output_file, program_name


def print_text_linux(file: str, output: Optional[str], debug: bool = False):
    global FILE_PROGRAM_PROC
    FILE_PROGRAM_PROC = subprocess.Popen(["gedit", file])
    logger.info(f"Priting text file {file}...")
    program_name = "gedit"
    wait_for_program(program_name, pid=FILE_PROGRAM_PROC.pid)

    output_file = start_print_process_visually(file, output, debug=debug)

    return output_file, program_name


def print_libreoffice_linux(file: str, output: Optional[str], debug: bool = False):
    global FILE_PROGRAM_PROC
    FILE_PROGRAM_PROC = subprocess.Popen(["libreoffice", "--norestore", "--nologo", file])
    logger.info(f"Priting LibreOffice file {file}...")
    program_name = "LibreOffice"
    wait_for_program(program_name, pid=FILE_PROGRAM_PROC.pid)

    output_file = start_print_process_visually(file, output, is_libreoffice=True, debug=debug)

    return output_file, program_name


def print_pdf_linux(file: str, output: Optional[str], debug: bool = False):
    global FILE_PROGRAM_PROC
    FILE_PROGRAM_PROC = subprocess.Popen(["firefox", "--new-window", file])
    logger.info(f"Priting PDF {file}...")
    basename = os.path.basename(file)
    program_name = f"{basename} — Mozilla Firefox"
    wait_for_program(program_name, pid=FILE_PROGRAM_PROC.pid)

    output_file = start_print_process_visually(file, output, is_firefox=True, debug=debug)

    return output_file, program_name


def open_pdf_linux(file: str, delay: Union[float, Tuple[float, float]], debug: bool = False):
    logger.info(f"Opening generated PDF {file}.")
    
    global PRINT_PROGRAM_PROC
    
    # PRINT_PROGRAM_PROC = subprocess.Popen(["evince", file])  # FIXME: This is not working
    PRINT_PROGRAM_PROC = subprocess.Popen(["firefox", "--new-window", file])
    window_name = f"{file} — Mozilla Firefox".split("/")[-1]  # Get the last part of the path
    wait_for_program(window_name, pid=PRINT_PROGRAM_PROC.pid)
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
    close_failsafe(PRINT_PROGRAM_PROC)
    sleep(1)


def print_visually_linux(
        files: List[str],
        delay: Union[float, Tuple[float, float]],
        output: Optional[str],
        debug: bool = False
    ):
    global FILE_PROGRAM_PROC
    
    for file in files:
        file = os.path.abspath(os.path.expanduser(file))
        if os.path.isdir(file):  # Get random file if a dir is provided
            file = get_random_file_from_dir(file)
            if file is None:
                return

        # Get the program based on the MIME type of the file
        mime_type = subprocess.run(['xdg-mime', 'query', 'filetype', file], capture_output=True, text=True).stdout.strip()
        program = subprocess.run(['xdg-mime', 'query', 'default', mime_type], capture_output=True, text=True).stdout.strip()
        logger.debug(f"File {file} has MIME type {mime_type} and default program {program}.")
    
        # Check if the file is an image
        if "eog" in program or mime_type.startswith('image/'):
            output_file, program = print_image_linux(file, output, debug)
        # Check if the file is a LibreOffice file
        elif "libreoffice" in program or mime_type in ['application/vnd.oasis.opendocument.text', 'application/vnd.oasis.opendocument.spreadsheet', 'application/vnd.oasis.opendocument.presentation', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.openxmlformats-officedocument.presentationml.presentation']:
            logger.info(f"Printing LibreOffice file {file}.")
            output_file, program = print_libreoffice_linux(file, output, debug)
        # Check if the file is a PDF
        elif "evince" in program or mime_type == 'application/pdf':
            logger.info(f"Printing PDF file {file}.")
            output_file, program = print_pdf_linux(file, output, debug)
        # Check if the file a text file
        else:
            logger.info(f"Printing text file {file}.")
            output_file, program = print_text_linux(file, output, debug)
        # else:
        #     output_file = ""

        open_pdf_linux(output_file, delay, debug)

        # Focus again on the original program
        res = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True)
        lines = res.stdout.splitlines()
        for line in lines:
            if program in line:
                wid = line.split()[0]  # Get the window ID
                subprocess.run(["wmctrl", "-ia", wid])
                logger.debug(f"Changing focus back to {program}.")
                break
        sleep(1)
        
        input_key('Alt+F4', debug=debug)  # Close the file viewer
        close_failsafe(FILE_PROGRAM_PROC)
        sleep(1)


def start_print_process_invisibly(
    file: str, 
    output: Optional[str],
    is_libreoffice: bool = False,
    debug: bool = False
) -> str:
    input_file = Path(file).resolve()
    pdf_dir = Path.home() / "PDF"
    pdf_dir.mkdir(exist_ok=True)

    if is_libreoffice:
        logger.debug("Converting LibreOffice file to PDF using soffice command.")
        subprocess.run([
            "libreoffice", 
            "--headless", 
            "--convert-to", 
            "pdf", 
            "--outdir", 
            str(pdf_dir), 
            str(input_file)], 
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        output_file = process_output(str(input_file), output)
        generated_pdf = pdf_dir / (input_file.stem + ".pdf")
        if generated_pdf.exists():
            if output_file != str(generated_pdf):
                shutil.move(str(generated_pdf), output_file)
                logger.debug(f"Moved generated PDF from {generated_pdf} to {output_file}.")
            else:
                logger.debug(f"Generated PDF is already in the desired location: {output_file}.")
            return output_file
        else:
            raise FileNotFoundError(f"LibreOffice conversion did not produce the expected PDF file {generated_pdf}.")

    # Get existing PDF files in the PDF directory
    existing_pdfs = set(pdf_dir.glob("*.pdf"))
    logger.debug(f"Existing PDF files in {pdf_dir}: {[str(p) for p in existing_pdfs]}.")

    # Start the printing process
    subprocess.run(
        ["lp", "-d", "PDF",  str(input_file)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True
    )

    # Wait for a new PDF file to appear in the PDF directory
    new_pdf = None
    timeout = 5  # iterations
    logger.debug(f"Waiting for the new PDF file to appear in {pdf_dir}...")
    for _ in range(timeout):
        sleep(1)  # wait for 1 second before checking again
        current_pdfs = set(pdf_dir.glob("*.pdf"))
        # print(f"Current PDF files in {pdf_dir}: {[str(p) for p in current_pdfs]}")
        new_files = current_pdfs - existing_pdfs
        logger.debug(f"New PDF files detected: {[str(p) for p in new_files]}.")
        # print(f"Raw new files: {new_files}")
        # print(f"Type of new_files: {type(new_files)}")

        # Filter possible candidates based on the input file name
        # for f in new_files:
        #     print(f"Checking new file {f} with name {f.name}")
        #     print(f"Is {f.name} equal to {input_file.name}? Is {str(f)} equal to {input_file}?")
        #     print()
        candidates = [f for f in new_files if input_file.name in f.name]
        logger.debug(f"Filtered candidates based on input file name: {[str(p) for p in candidates]}.")
        if candidates:
            # Take the most recently modified candidate
            new_pdf = max(candidates, key=lambda f: f.stat().st_mtime)
            logger.debug(f"Selected new PDF file: {new_pdf}.")
            break
        print()

    if new_pdf is None:
        raise FileNotFoundError(f"No new PDF file was created in the PDF directory for input file {file}.")
    
    # Check what output is: directory or filename
    output_file = process_output(str(input_file), output)

    # Move the new PDF to the desired output location
    if output_file != str(new_pdf):
        shutil.move(str(new_pdf), output_file)
        logger.debug(f"Moved generated PDF from {new_pdf} to {output_file}.")
    else:
        logger.debug(f"Generated PDF is already in the desired location: {output_file}.")
    
    return output_file



def print_invisibly_linux(
    files: List[str],
    output: Optional[str],
    debug: bool = False
):
    for file in files:
        file = os.path.abspath(os.path.expanduser(file))
        if os.path.isdir(file):  # Get random file if a dir is provided
            file = get_random_file_from_dir(file)
            if file is None:
                return

        # Get the program based on the MIME type of the file
        mime_type = subprocess.run(['xdg-mime', 'query', 'filetype', file], capture_output=True, text=True).stdout.strip()
        program = subprocess.run(['xdg-mime', 'query', 'default', mime_type], capture_output=True, text=True).stdout.strip()
        logger.debug(f"File {file} has MIME type {mime_type} and default program {program}.")

        # Check if the file is a LibreOffice file
        if "libreoffice" in program or mime_type in ['application/vnd.oasis.opendocument.text', 'application/vnd.oasis.opendocument.spreadsheet', 'application/vnd.oasis.opendocument.presentation', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.openxmlformats-officedocument.presentationml.presentation']:
            logger.info(f"Printing LibreOffice file {file}.")
            output_file = start_print_process_invisibly(file, output, is_libreoffice=True, debug=debug)
        else:
            logger.info(f"Printing file {file} using lp command.")
            output_file = start_print_process_invisibly(file, output, debug=debug)

        # open_pdf_linux(output_file, delay, debug)  # Not needed in invisible mode


def print_in_linux(
        visible: bool, 
        files: List[str],
        delay: Union[float, Tuple[float, float]],
        output: Optional[str]
    ):
    if visible:
        logger.debug(f"Trying to acquire input lock on {LOCK_INPUT.lock_file}.")
        start_t = time.perf_counter()
        with LOCK_INPUT.acquire():
            waited_t = time.perf_counter() - start_t
            if waited_t > CONTENTION_THRESHOLD:
                logger.debug(f"Input lock acquired after waiting {waited_t:.2f} seconds (contention detected).")
            else:
                logger.debug(f"Input lock acquired immediately (no contention).")
            
            disable_user_input()
            
            logger.debug(f"Trying to acquire lock on {LOCK.lock_file}.")
            start_t = time.perf_counter()
            with LOCK.acquire():
                waited_t = time.perf_counter() - start_t
                if waited_t > CONTENTION_THRESHOLD:
                    logger.debug(f"Lock acquired after waiting {waited_t:.2f} seconds (contention detected).")
                else:
                    logger.debug(f"Lock acquired immediately (no contention).")
                    
                print_visually_linux(files, delay, output)
                enable_user_input()
    else:
        print_invisibly_linux(files, output)


# Input control

def get_user_input_device_ids():
    EXCLUDED_KEYWORDS = [
        "Virtual core",
        "XTEST",
        "Power Button",
        "Sleep Button",
        "Video Bus"
    ]
    
    result = subprocess.run(
        ["xinput", "list"],
        stdout=subprocess.PIPE,
        text=True
    )

    device_ids = []
    for line in result.stdout.splitlines():
        match = re.search(r'id=(\d+)', line)
        if not match:
            continue

        device_id = int(match.group(1))
        name = line.split("id=")[0].strip()

        if any(keyword in name for keyword in EXCLUDED_KEYWORDS):
            continue

        device_ids.append(device_id)
    
    logger.debug(f"Detected user input devices: {device_ids}")

    return device_ids


def _set_input_devices(enabled: bool):
    """
    Enable or disable user input devices using xinput.
    """
    # USER_INPUT_DEVICE_IDS = [9, 10, 11]
    
    action = "enable" if enabled else "disable"
    for dev_id in get_user_input_device_ids():
        try:
            res = subprocess.run(
                ["xinput", action, str(dev_id)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True
            )
            logger.debug(f"xinput {action} {dev_id}")
            if res.returncode != 0:
                logger.warning(f"xinput non-zero return code: {res.returncode}")
                logger.error(f"xinput error: {res.stderr}")
        except Exception as e:
            logger.error(f"Failed to {action} device {dev_id}: {e}")
    sleep(2)  # Fail-safe


def disable_user_input():
    logger.debug("Disabling user input devices.")
    _set_input_devices(False)


def enable_user_input():
    logger.debug("Enabling user input devices.")
    _set_input_devices(True)



def init(check_display: bool = False):
    if check_display and get_system() == 'Linux':
        _ensure_graphical_session()
    _check_and_import_dependencies()
    _setup_locks()


def main():
    parser = argparse.ArgumentParser(
        prog='printer-simulation',
        description='Simulate activity printing diffent types of files, such as text files, images, etc.',
    )

    # Make a visible and invisible arguments, they are mutually exclusive
    parser.add_argument('files', type=str, help='Files to print. If it is a directory, a random file will be picked.', nargs='+')
    parser.add_argument('--visible', action='store_true', help='Prints visually (using the GUI).', default=True)
    parser.add_argument('--invisible', action='store_false', dest="visible", help='Prints through commands')
    parser.add_argument('--output', '-O', type=str, required=False, help='Output directory to save files to. If not a directory, it will be used as a filename. If not provided, the directory where the input files are will be used.')
    parser.add_argument('--min-delay', type=float, default=None, help='Minimum delay between actions (in seconds).')
    parser.add_argument('--max-delay', type=float, default=None, help='Maximum delay between actions (in seconds).')
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

    init(check_display=bool(args.visible))
    
    try:
        logger.debug(f"Printing will be {'visible' if args.visible else 'invisible'}.")

        output_check = os.path.abspath(os.path.expanduser(args.output)) if args.output is not None else None
        if output_check and not os.path.isdir(output_check) and len(args.files) > 1:
            logger.error("If multiple files are provided, the output must be a directory.")
            exit(1)

        if args.visible:
            # Visible mode
            if args.min_delay is None and args.max_delay is None and args.delay is None:
                args.min_delay = 5.0
                args.max_delay = 10.0
                delay = (args.min_delay, args.max_delay)
                logger.info("No delay provided, using default min-delay=5.0 and max-delay=10.0 seconds.")
            elif args.delay is not None:
                if args.delay < 0:
                    logger.error("Delay must be a positive number.")
                    exit(1)
                
                if args.min_delay is not None or args.max_delay is not None:
                    logger.warning("Both delay and min-delay/max-delay provided, using delay and ignoring min-delay and max-delay.")
                
                args.min_delay = None
                args.max_delay = None
                delay = args.delay
            else:
                if args.min_delay is None and args.max_delay is not None:
                    args.delay = args.max_delay
                    args.max_delay = None
                    if args.delay < 0:
                        logger.error("Max delay must be a positive number.")
                        exit(1)
                    logger.warning(f"Only max-delay provided, using delay={args.delay} seconds.")
                    delay = args.delay
                elif args.min_delay is not None and args.max_delay is None:
                    args.delay = args.min_delay
                    args.min_delay = None
                    if args.delay < 0:
                        logger.error("Min delay must be a positive number.")
                        exit(1)
                    logger.warning(f"Only min-delay provided, using delay={args.delay} seconds.")
                    delay = args.delay
                else:
                    if args.min_delay < 0 or args.max_delay < 0:
                        logger.error("Min and max delay must be positive numbers.")
                        exit(1)
                    elif args.min_delay == args.max_delay:
                        args.delay = args.min_delay
                        args.min_delay = None
                        args.max_delay = None
                        logger.info(f"Min-delay and max-delay are the same, using delay={args.delay} seconds.")
                        delay = args.delay
                    elif args.min_delay > args.max_delay:
                        logger.error("Min delay must be less than or equal to max delay.")
                        exit(1)
                    else:
                        delay = (args.min_delay, args.max_delay)
            logger.debug(f"Using delay: {delay} seconds.")
        else:
            # Invisible mode
            if args.delay is not None or args.min_delay is not None or args.max_delay is not None:
                logger.warning("Delay arguments are ignored in invisible mode.")
            delay = 0.0  # No delay needed in invisible mode
        
        # Check the OS
        if get_system() == 'Windows':
            logger.debug("Running in Windows.")
            print_in_windows(args.visible, args.files, args.min_delay, args.max_delay, args.delay, args.output)
        else:
            logger.debug("Running in Linux.")
            print_in_linux(args.visible, args.files, delay, args.output)

    except KeyboardInterrupt:
        logger.warning("printer-simulation interrupted by user. Closing any open processes...")
        if FILE_PROGRAM_PROC:
            close_failsafe(FILE_PROGRAM_PROC)
        if PRINT_PROGRAM_PROC:
            close_failsafe(PRINT_PROGRAM_PROC)
            
        enable_user_input()
    finally:
        logger.info("Finishing printer-simulation.")


if __name__ == '__main__':
    main()
else:
    init()
