import os
import random
import subprocess
import re
import logging
import argparse
import shutil

from typing import List, Optional, Tuple, Union
from logging.handlers import RotatingFileHandler

path = os.path.join(os.path.expanduser('~'), ".config", "printer-simulation")
os.makedirs(path, exist_ok=True)

try:
    import pyautogui
    import pyperclip
except Exception as e:
    import traceback
    import datetime

    error_file = os.path.join(path, "error_printer-simulation.log")
    with open(error_file, "a") as file:
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


format_str = '%(asctime)s - %(levelname)s - %(message)s'
formatter = logging.Formatter(format_str)
logger = logging.getLogger(__name__)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.WARNING)
logger.addHandler(console_handler)


def get_system():
    if os.name == 'nt':
        return 'Windows'
    else:
        return 'Linux'
    

def wait_for_program(program: str):
    logger.debug(f"Waiting for {program} to load")
    while True:
        result = subprocess.run(['wmctrl', '-l'], capture_output=True, text=True)
        if program in result.stdout:
            logger.debug(f"{program} is loaded")
            break
        pyautogui.sleep(1)  # Wait for 1 second before checking again
    pyautogui.sleep(2)  # Fail-safe sleep to ensure the program is fully loaded


def split_path_regex(path: str) -> List[str]:
    # Regex to split path elements such as "/" or "~"
    pattern = r'(~/|/|[^/]+)'
    return re.findall(pattern, path)


def print_in_windows(
        visible: bool, 
        files: List[str],
        min_delay: float,
        max_delay: float,
        delay: float,
        output: Optional[str]
    ):
    pass


def sleep_action(delay: Union[float, Tuple[float, float]], extra_delay: float = 0.0):
    if isinstance(delay, tuple):
        min_delay, max_delay = delay
        delay = random.uniform(min_delay, max_delay)
    logger.debug(f"Sleeping for {delay} seconds (extra {extra_delay} seconds)")
    pyautogui.sleep(delay + extra_delay)


def process_output(file: str, output: Optional[str] = None, is_libreoffice: bool = False) -> str:
    if output:
        output = os.path.expanduser(output)
        if os.path.isdir(output):
            logger.debug("Output is a directory, using the same filename as the input file")
            output_file = os.path.join(output, os.path.basename(file) + '.pdf')
        else:
            logger.debug("Output is a filename")
            # If the output is a plain filename, output_file should be in the same directory as the input file
            # If not, it will be the output filename
            if os.path.isdir(os.path.dirname(output)):
                output_file = output
            else:
                output_file = os.path.join(os.path.dirname(file), output)
        
        if not is_libreoffice:
            # Move the file to the output directory
            logger.debug(f"Moving the file to {output_file}")
            shutil.move(f"{file}.pdf", output_file)
    else:
        logger.debug("No output directory provided, using the same directory as the input file")
        output_file = file + '.pdf'
    
    return output_file


def start_print_process_visually(
        file: str, 
        output: Optional[str], 
        delay: Union[float, Tuple[float, float]], 
        is_libreoffice: bool = False
    ) -> str:
    # Start the print dialog
    logger.debug(f"Starting the print dialog for {file}")
    pyautogui.sleep(2)
    with pyautogui.hold('ctrl'):
        pyautogui.press('p')
    pyautogui.sleep(3)

    # Go to the printers list
    logger.debug("Selecting the printer")
    if is_libreoffice:
        with pyautogui.hold('shift'):
            pyautogui.press('tab', interval=0.5, presses=5)
        
        # Change the printer to print to a file
        pyautogui.sleep(1)
        pyautogui.press('space')
        pyautogui.sleep(1)
        pyautogui.write('imprimir', interval=0.1)
        pyautogui.press('enter', interval=0.5, presses=2)
    else:
        pyautogui.press('tab')
        pyautogui.sleep(1)

        # Write "imprimir" to ensure the right printer is selected
        pyautogui.write('imprimir', interval=0.1)

        # Now, go to the filename field
        logger.debug("Selecting the filename")
        pyautogui.press('tab', presses=2, interval=0.5)

        # Press Enter to write the filename
        pyautogui.press('enter')
        pyautogui.sleep(1)
        
    # Write the filename
    # Check the output (is it a directory or a filename?)
    output_file = process_output(file, output, is_libreoffice)
    if is_libreoffice:
        # output_file = process_output(file, output, is_libreoffice)
        parts = split_path_regex(output_file)
    else:
        parts = split_path_regex(f"{file}.pdf")
    logger.debug(f"Split input path: {parts}")

    pyautogui.hotkey('ctrl', 'a')
    for part in parts:
        # Fix to writing special characters
        if '/' in part or '~' in part:
            pyperclip.copy(part)
            pyautogui.sleep(0.05)
            pyautogui.hotkey('ctrl', 'v')
            pyautogui.sleep(0.05)
        else:
            pyautogui.write(part, delay)

    pyautogui.sleep(1)
    pyautogui.press('enter')  # Select the filename
    pyautogui.sleep(1)
    logger.debug("Pressing the Print button")

    if is_libreoffice:
        # These are needed in case of confirmation dialog on an existing file
        pyautogui.press('tab')
        pyautogui.press('enter')
        pyautogui.hotkey('ctrl', 'z')  # Needed to undo in case of printing a text file
        pyautogui.hotkey('ctrl', 'z')
        pyautogui.sleep(1)
    if not is_libreoffice:
        with pyautogui.hold('shift'): # Go to the "Print" button
            pyautogui.press('tab', presses=3, interval=0.25)
        pyautogui.press('enter', presses=2, interval=0.5)  # Two presses in case of confirmation dialog of an existing file
        pyautogui.hotkey('ctrl', 'z')  # Needed to undo in case of printing a text file
        pyautogui.sleep(1)

    # Check the output (is it a directory or a filename?)
    # output_file = process_output(file, output)

    return output_file



def print_image_linux(file: str, output: Optional[str], delay: Union[float, Tuple[float, float]]):
    subprocess.Popen(["eog", file])
    logger.debug(f"Priting image {file}")
    # In case of eog, the program name is the name of the file (just the last part)
    wait_for_program(os.path.basename(file))

    output_file = start_print_process_visually(file, output, delay)

    return output_file


def print_text_linux(file: str, output: Optional[str], delay: Union[float, Tuple[float, float]]):
    subprocess.Popen(["gedit", file])
    logger.debug(f"Priting text file {file}")
    wait_for_program("gedit")

    output_file = start_print_process_visually(file, output, delay)

    return output_file

def print_libreoffice_linux(file: str, output: Optional[str], delay: Union[float, Tuple[float, float]]):
    subprocess.Popen(["libreoffice", file])
    logger.debug(f"Priting LibreOffice file {file}")
    wait_for_program("LibreOffice")

    output_file = start_print_process_visually(file, output, delay, is_libreoffice=True)

    return output_file



def open_pdf_linux(file: str, delay: Union[float, Tuple[float, float]]):
    logger.debug(f"Opening PDF {file}")
    # subprocess.Popen(["evince", file])  # FIXME: This is not working
    subprocess.Popen(["firefox", "--new-window", file])
    window_name = f"{file} — Mozilla Firefox".split("/")[-1]  # Get the last part of the path
    wait_for_program(window_name)
    logger.debug("Simulating reading the PDF")
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
            logger.debug(f"Changing focus to {window_name}")
            break
    pyautogui.sleep(1)

    # Close the evince/firefox window
    pyautogui.hotkey('alt', 'f4')
    pyautogui.sleep(1)


def print_visually_linux(
        files: List[str],
        min_delay: float,
        max_delay: float,
        delay: float,
        output: Optional[str]
    ):
    for file in files:
        # Check if the file is an image
        if file.endswith('.png') or file.endswith('.jpg') or file.endswith('.jpeg'):
            logger.debug(f"Printing image {file}")
            output_file = print_image_linux(file, output, 0.125)
        # Check if the file a text file
        elif file.endswith('.txt') or file.endswith('.md') or file.endswith('.json'):
            logger.debug(f"Printing text file {file}")
            output_file = print_text_linux(file, output, 0.125)
        # Check if the file a LibreOffice file
        elif file.endswith('.odt') or file.endswith('.ods') or file.endswith('.odp'):
            logger.debug(f"Printing LibreOffice file {file}")
            output_file = print_libreoffice_linux(file, output, 0.125)
        else:
            output_file = ""

        open_pdf_linux(output_file, (min_delay, max_delay))
        os.system("wmctrl -xa gedit.Gedit")
        pyautogui.sleep(1)
        pyautogui.hotkey('alt', 'f4')
        pyautogui.sleep(1)



def print_in_linux(
        visible: bool, 
        files: List[str],
        min_delay: float,
        max_delay: float,
        delay: float,
        output: Optional[str]
    ):
    if visible:
        print_visually_linux(files, min_delay, max_delay, delay, output)
    else:
        pass



def main():
    parser = argparse.ArgumentParser(
        prog='printer-simulation',
        description='Simulate activity printing diffent types of files, such as text files, images, etc.',
    )

    # Make a visible and invisible arguments, they are mutually exclusive
    parser.add_argument('--visible', action='store_true', help='Make the actions visible.', default=True)
    parser.add_argument('--invisible', action='store_true', help='Make the actions invisible.', default=False)
    parser.add_argument('--output', '-O', type=str, required=False, help='Output directory to save files to. If not a directory, it will be used as a filename. If not provided, the directory where the input files are will be used.')
    parser.add_argument('files', type=str, help='Files to print.', nargs='+')
    parser.add_argument('--min-delay', type=float, default=5.0, help='Minimum delay between actions (in seconds).')
    parser.add_argument('--max-delay', type=float, default=10.0, help='Maximum delay between actions (in seconds).')
    parser.add_argument('--delay', type=float, default=None, help='Fixed delay between actions (in seconds). Overrides --min-delay and --max-delay.')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode.')

    # Parse arguments
    args = parser.parse_args()


    file_handler = RotatingFileHandler(
        os.path.join(path, 'printer-simulation.log'),
        maxBytes=1024*1024,
        backupCount=3
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    if args.debug:
        logger.setLevel(logging.DEBUG)
        console_handler.setLevel(logging.DEBUG)
        file_handler.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    # Preprocess options
    visible = args.visible or not args.invisible
    logger.debug(f"Printing will be {'visible' if visible else 'invisible'}")

    # Set the current directory as the input (without the last part)
    input_dir = os.path.dirname(args.files[0])
    os.chdir(input_dir)
    logger.debug(f"Woring directory: {input_dir}")

    # Check the OS
    if get_system() == 'Windows':
        logger.debug("Running in Windows")
        print_in_windows(visible, args.files, args.min_delay, args.max_delay, args.delay, args.output)
    else:
        logger.debug("Running in Linux")
        print_in_linux(visible, args.files, args.min_delay, args.max_delay, args.delay, args.output)


if __name__ == '__main__':
    main()
