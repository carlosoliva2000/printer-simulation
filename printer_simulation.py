import json
import os
import random
import pyautogui
import subprocess
import string
import logging
import argparse
import shutil

import pyperclip
import re

from typing import List, Optional, Tuple, Union


logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_system():
    if os.name == 'nt':
        return 'Windows'
    else:
        return 'Linux'


def split_path_regex(path: str) -> List[str]:
    # Regex to split path elements such as "/" or "~"
    pattern = r'(~/|/|[^/]+)'
    return re.findall(pattern, path)


def load_words() -> List[str]:
    logger.debug("Loading words")
    try:
        # Get the first directory in /opt/ghosts if it exists
        json_path = os.path.join(
            '/opt/ghosts', 
            os.listdir('/opt/ghosts')[0], 
            'ghosts-client/config/dictionary.json'
        )

        with open(json_path, 'r', encoding='utf-8-sig') as file:
            words = json.load(file)
        logger.debug("Words loaded from remote dictionary")
    except FileNotFoundError: # If not, use the local dictionary
        try:
            with open('dictionary.json', 'r', encoding='utf-8-sig') as file:
                words = json.load(file)
            logger.debug("Words loaded from local dictionary")
        except FileNotFoundError:
            logger.error("No dictionary found in the current directory (where is the dictionary.json file?)")
            exit(1)

    # Ensure all words are strings
    words = [str(word) for word in words]
    return words


def generate_paragraph(
        words: List[str],
        min_sentences: int,
        max_sentences: int,
        min_words: int,
        max_words: int
    ) -> str:
    num_sentences = random.randint(min_sentences, max_sentences)  # Number of sentences in the paragraph
    sentences = []
    
    for _ in range(num_sentences):
        num_words = random.randint(min_words, max_words)  # Number of words in the sentence
        sentence_words = random.choices(words, k=num_words)
        # print(sentence_words)
        sentence = ' '.join(sentence_words).capitalize() + '.'  # Join words and capitalize the first letter
        sentences.append(sentence)
    
    return ' '.join(sentences)


def generate_text(
        words: List[str],
        min_paragraphs: int,
        max_paragraphs: int,
        min_sentences: int,
        max_sentences: int,
        min_words: int,
        max_words: int
    ) -> str:
    num_paragraphs = random.randint(min_paragraphs, max_paragraphs)  # Number of paragraphs in the text
    paragraphs = [generate_paragraph(words, min_sentences, max_sentences, min_words, max_words) for _ in range(num_paragraphs)]
    return '\n\n'.join(paragraphs)  # Join paragraphs with two newlines


def generate_filename(
        min_filename_length: int,
        max_filename_length: int
    ) -> str:
    length = random.randint(min_filename_length, max_filename_length)  # Length of the filename
    characters = string.ascii_letters + string.digits  # Mix of letters (upper and lower case) and digits
    filename = ''.join(random.choice(characters) for _ in range(length)) + '.txt'
    return filename


def save_file(path: str, filename: str, interval: float):
    path = os.path.join(path, filename)

    pyautogui.hotkey('ctrl', 's')
    pyautogui.sleep(1)  # Wait for the save dialog to appear
    parts = split_path_regex(path)
    logger.debug(f"Split path: {parts}")

    for part in parts:
        # Fix to writing special characters
        if '/' in part or '~' in part:
            pyperclip.copy(part)
            pyautogui.sleep(0.05)
            pyautogui.hotkey('ctrl', 'v')
            pyautogui.sleep(0.05)
        else:
            pyautogui.write(part, interval)

    pyautogui.sleep(1)  # Wait for the save dialog to appear
    pyautogui.press('enter')
    pyautogui.sleep(2)



def random_execution(args: argparse.Namespace, subparsers: argparse._SubParsersAction) -> argparse.Namespace:
    # Check if should execute the command
    if random.random() > args.execution / 100:
        logger.info("Due to the probabilities, the command will not be executed.")
        print("Due to the probabilities, the command will not be executed.")
        exit(0)

    # Check if the probabilities sum to 100
    if args.create + args.edit + args.view + args.delete != 100:
        logger.error("The sum of the probabilities of the verbs (create, edit, view, delete) must be 100.")
        exit(1)

    verbs = ['create', 'edit', 'view', 'delete']
    probabilities = [
        args.create / 100,
        args.edit / 100,
        args.view / 100,
        args.delete / 100
    ]
    
    # Choose a random command based on the probabilities
    chosen_command = random.choices(verbs, probabilities)[0]
    
    # Get and call the chosen command parser
    # command_parser = parser._subparsers._parser_map[chosen_command]
    command_parser: argparse.ArgumentParser = subparsers.choices[chosen_command]
    # command_args, remaining_args = command_parser.parse_known_args(args.input, args.output)
    command_args = command_parser.parse_known_args(namespace=args)[0]

    command_args.command = chosen_command
    logger.debug(f'Chosen command "{chosen_command}" with args: {command_args}')

    return command_args


def delete_process(input_dir: str):
    # Choose a .txt random file to delete
    # TODO: add more types or use an argument to determine what to delete
    files = [f for f in os.listdir(input_dir) if f.endswith('.txt')]
    if not files:
        logger.debug(f"No files found in {input_dir}")
        return
    
    file_to_delete = random.choice(files)
    logger.debug(f"Deleting {file_to_delete}")
    os.remove(os.path.join(input_dir, file_to_delete))


def view_process(input_dir: str, min_time: int, max_time: int, fixed_time: Optional[int] = None):
    # Choose a .txt random file to view
    files = [f for f in os.listdir(input_dir) if f.endswith('.txt')]
    if not files:
        logger.debug(f"No files found in {input_dir}")
        return
    
    if fixed_time:
        time = fixed_time
    else:
        time = random.randint(min_time, max_time)
    
    file_to_view = random.choice(files)
    logger.debug(f"Viewing {file_to_view} for {time} seconds")

    # Open gedit
    subprocess.Popen(['gedit', os.path.join(input_dir, file_to_view)])

    # Ensure the focus is on the gedit window
    pyautogui.sleep(3)
    os.system("wmctrl -xa gedit.Gedit")

    # Wait for the time
    pyautogui.sleep(time)

    # Ensure the focus is on the gedit window again
    os.system("wmctrl -xa gedit.Gedit")
    pyautogui.sleep(1)
    logger.debug("Closing gedit")

    # Close gedit
    pyautogui.hotkey('alt', 'f4')


def edit_process(
        input_dir: str, 
        min_paragraphs: int, 
        max_paragraphs: int, 
        min_sentences: int, 
        max_sentences: int, 
        min_words: int, 
        max_words: int,
        interval: float
    ):
    # Choose a .txt random file to edit
    files = [f for f in os.listdir(input_dir) if f.endswith('.txt')]
    if not files:
        logger.debug(f"No files found in {input_dir}")
        return
    
    file_to_edit = random.choice(files)
    logger.debug(f"Editing {file_to_edit}")

    # Load the words
    words = load_words()

    # Generate the text
    generated_text = generate_text(words, min_paragraphs, max_paragraphs, min_sentences, max_sentences, min_words, max_words)

    # Open gedit
    subprocess.Popen(['gedit', os.path.join(input_dir, file_to_edit)])

    # Ensure the focus is on the gedit window
    pyautogui.sleep(3)
    os.system("wmctrl -xa gedit.Gedit")

    # Go to the end of the file
    pyautogui.hotkey('ctrl', 'end')
    pyautogui.write('\n\n', interval=interval)

    # Write the generated text
    pyautogui.sleep(3)
    pyautogui.write(generated_text, interval=interval)
    pyautogui.sleep(1)

    # Save the file
    pyautogui.hotkey('ctrl', 's')
    pyautogui.sleep(2)

    # Close gedit
    pyautogui.hotkey('alt', 'f4')


def create_process(
        output_dir: str,
        min_paragraphs: int,
        max_paragraphs: int,
        min_sentences: int,
        max_sentences: int,
        min_words: int,
        max_words: int,
        min_filename_length: int,
        max_filename_length: int,
        interval: float
    ):
    # Load the words
    words = load_words()

    # Generate the text
    generated_text = generate_text(words, min_paragraphs, max_paragraphs, min_sentences, max_sentences, min_words, max_words)

    # Generate the filename
    random_filename = generate_filename(min_filename_length, max_filename_length)
    logger.debug(f"Generating {random_filename}")

    # Open gedit
    subprocess.Popen(['gedit'])

    # Ensure the focus is on the gedit window
    pyautogui.sleep(3)
    os.system("wmctrl -xa gedit.Gedit")

    # Write the generated text
    pyautogui.write(generated_text, interval=interval)
    pyautogui.sleep(1)

    # Save the file
    save_file(output_dir, random_filename, interval)

    # Close gedit
    pyautogui.hotkey('alt', 'f4')



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


def process_output(file: str, output: Optional[str] = None) -> str:
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
        
        # Move the file to the output directory
        logger.debug(f"Moving the file to {output_file}")
        shutil.move(f"{file}.pdf", output_file)
    else:
        logger.debug("No output directory provided, using the same directory as the input file")
        output_file = file + '.pdf'
    
    return output_file


def start_print_process_visually(file: str, output: Optional[str], delay: Union[float, Tuple[float, float]]):
    # Start the print dialog
    logger.debug(f"Starting the print dialog for {file}")
    pyautogui.sleep(2)
    with pyautogui.hold('ctrl'):
        pyautogui.press('p')
    pyautogui.sleep(3)

    # Go to the printers list
    logger.debug("Selecting the printer")
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
    with pyautogui.hold('shift'): # Go to the "Print" button
        pyautogui.press('tab', presses=3, interval=0.25)
    pyautogui.press('enter', presses=2, interval=0.5)  # Two presses in case of confirmation dialog of an existing file
    pyautogui.hotkey('ctrl', 'z')  # Needed to undo in case of printing a text file
    pyautogui.sleep(1)

    # Check the output (is it a directory or a filename?)
    output_file = process_output(file, output)

    return output_file



def print_image_linux(file: str, output: Optional[str], delay: Union[float, Tuple[float, float]]):
    subprocess.Popen(["eog", file])
    logger.debug(f"Priting image {file}")

    output_file = start_print_process_visually(file, output, delay)

    return output_file


def print_text_linux(file: str, output: Optional[str], delay: Union[float, Tuple[float, float]]):
    subprocess.Popen(["gedit", file])
    logger.debug(f"Priting text file {file}")

    output_file = start_print_process_visually(file, output, delay)

    return output_file



def open_pdf_linux(file: str, delay: Union[float, Tuple[float, float]]):
    logger.debug(f"Opening PDF {file}")
    subprocess.Popen(["evince", file])
    logger.debug("Simulating reading the PDF")
    sleep_action(delay)  # TODO: add actions such as zooming, scrolling, etc.

    # Ensure the focus is on the evince window
    os.system("wmctrl -xa evince.Evince")
    pyautogui.sleep(1)

    # Close the evince window
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
        else:
            output_file = ""

        open_pdf_linux(output_file, (min_delay, max_delay))
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


    if args.debug:
        logger.setLevel(logging.DEBUG)

    # Preprocess options
    visible = args.visible or not args.invisible
    logger.debug(f"Printing will be {'visible' if visible else 'invisible'}")

    # Check the OS
    if get_system() == 'Windows':
        logger.debug("Running in Windows")
        print_in_windows(visible, args.files, args.min_delay, args.max_delay, args.delay, args.output)
    else:
        logger.debug("Running in Linux")
        print_in_linux(visible, args.files, args.min_delay, args.max_delay, args.delay, args.output)


if __name__ == '__main__':
    main()
