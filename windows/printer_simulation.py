import os
import random
import subprocess
import re
import logging
import argparse

from time import sleep
from pathlib import Path
from typing import List, Optional, Tuple, Union
from filelock import FileLock
from logging.handlers import RotatingFileHandler


# Logging setup

LOG_PATH = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "printer-simulation")
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



# Lock setup

def _setup_locks():
    global LOCK, LOCK_INPUT
    lock_dir = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
    os.makedirs(lock_dir, exist_ok=True)
    LOCK = FileLock(os.path.join(lock_dir, ".printer.lock"))
    LOCK_INPUT = FileLock(os.path.join(lock_dir, ".input.lock"))


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


# Windows printing functions (not implemented yet)

def print_in_windows(
        visible: bool, 
        files: List[str],
        delay: Union[float, Tuple[float, float]],
        output: Optional[str]
    ):
    logger.debug(f"Trying to acquire input lock on {LOCK_INPUT.lock_file}.")
    with LOCK_INPUT.acquire():
        logger.debug(f"Trying to acquire lock on {LOCK.lock_file}.")
        with LOCK.acquire():
            print_prompting_in_windows(files, delay, output)


def open_pdf_windows(file: str, delay: Union[float, Tuple[float, float]]):
    """
    Opens a PDF file with the default program in Windows, waits for the window, and simulates reading.
    """
    file_path = Path(file).resolve()
    
    # 1. Detect default program for PDF
    try:
        # Obtener la extensión y la asociación
        ext = ".pdf"
        assoc = subprocess.run(['cmd', '/c', f'assoc {ext}'], capture_output=True, text=True, shell=True)
        # filetype = assoc.stdout.strip().split('=')[1]  # Devuelve algo como "AcroExch.Document.DC" o "MSEdgePDF"
        filetype = "MSEdgePDF"
        
        ftype = subprocess.run(['cmd', '/c', f'ftype {filetype}'], capture_output=True, text=True, shell=True)
        prog_cmd = ftype.stdout.strip().split('=')[1]  # Devuelve algo como '"C:\\Program Files (x86)\\Microsoft\\Edge\\msedge.exe" "%1"'
        # Extraer solo el ejecutable
        match = re.match(r'"([^"]+)"', prog_cmd)
        exe_path = match.group(1) if match else prog_cmd.split()[0]
        logger.debug(f"Detected default PDF program: {exe_path}")
    except Exception as e:
        logger.warning(f"Could not detect default PDF program, falling back to Edge. Error: {e}")
        exe_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

    # 2. Abrir el PDF
    proc = subprocess.Popen([exe_path, str(file_path)], shell=False)
    window_name = file_path.name  # Simple heurística para esperar la ventana
    logger.info(f"Opening PDF {file_path} in {exe_path}...")

    # 3. Esperar a que la ventana aparezca
    import time
    timeout = 10
    for _ in range(timeout):
        try:
            result = subprocess.run(['powershell', '-Command', 'Get-Process | Select-Object -Property MainWindowTitle,ProcessName'], capture_output=True, text=True)
            if file_path.name in result.stdout:
                logger.debug(f"Window for {file_path.name} detected.")
                break
        except Exception as e:
            pass
        time.sleep(1)
    
    # 4. Simular lectura si es necesario
    if isinstance(delay, tuple):
        sleep_time = random.uniform(*delay)
    else:
        sleep_time = delay
    logger.info(f"Simulating reading PDF for {sleep_time} seconds...")
    sleep(sleep_time)

    # 5. Cerrar la ventana
    # input_key('Alt+F4')
    # logger.debug(f"Closed PDF {file_path.name} window.")



def print_prompting_in_windows(
        files: List[str],
        delay: Union[float, Tuple[float, float]],
        output: Optional[str]
    ):
    for file in files:
        file_path = Path(file).resolve()
        if output:
            output_path = Path(output).resolve()
            if output_path.is_dir():
                output_file = output_path / (file_path.stem + ".pdf")
            else:
                output_file = output_path
        else:
            output_file = file_path.with_suffix(".pdf")
        
        if output_file.exists():
            logger.debug(f"Output file {output_file} exists, will press Alt+S to overwrite.")
            overwrite = True
        else:
            overwrite = False

        logger.info(f"Printing {file_path} to {output_file}...")

        cmd = [
            "powershell",
            "-Command",
            f"Start-Process -FilePath '{file_path}' -Verb Print"
        ]
        subprocess.run(cmd, check=True)

        sleep(1.0)

        seq = []

        if overwrite:
            seq.append("K,Alt+S")  # Overwrite

        seq.append(f'T,"{str(output_file)}"')
        seq.append("K,Enter")

        args = {"--press-interval": 0.5, "--typing-interval": 0.1, "--sleep": 0.5}
        input_keyboard_sequence(seq, args)
        
        logger.debug(f"Finished printing {file_path}.")
        sleep(2.0)
        open_pdf_windows(file, delay)
        

def init():
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

    init()

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
        print_in_windows(args.visible, args.files, delay, args.output)
    else:
        logger.debug("Running in Linux.")
        pass
        # print_in_linux(args.visible, args.files, delay, args.output)

    logger.info("Finishing printer-simulation.")


if __name__ == '__main__':
    main()
else:
    init()
