import shutil
from getpass import getpass

from telethon import RPCError, TelegramClient
from telethon.tl.types import UpdateShortChatMessage, UpdateShortMessage
from telethon.utils import get_display_name, get_input_peer

# Get the (current) number of lines in the terminal
cols, rows = shutil.get_terminal_size()


def print_title(title):
    # Clear previous window
    print('\n')
    available_cols = cols - 2  # -2 sincewe omit '┌' and '┐'
    print('┌{}┐'.format('─' * available_cols))
    print('│{}│'.format(title.center(available_cols)))
    print('└{}┘'.format('─' * available_cols))


def bytes_to_string(byte_count):
    """Converts a byte count to a string (in KB, MB...)"""
    suffix_index = 0
    while byte_count >= 1024:
        byte_count /= 1024
        suffix_index += 1

    return '{:.2f}{}'.format(byte_count,
                             [' bytes', 'KB', 'MB', 'GB', 'TB'][suffix_index])


class InteractiveTelegramClient(TelegramClient):
    def __init__(self, session_user_id, user_phone, api_id, api_hash):
        print_title('Initialization')

        print('Initializing interactive example...')
        super().__init__(session_user_id, api_id, api_hash)

        # Store all the found media in memory here,
        # so it can be downloaded if the user wants
        self.found_media = set()

        print('Connecting to Telegram servers...')
        self.connect()

        # Then, ensure we're authorized and have access
        if not self.is_user_authorized():
            print('First run. Sending code request...')
            self.send_code_request(user_phone)

            code_ok = False
            while not code_ok:
                code = input('Enter the code you just received: ')
                try:
                    code_ok = self.sign_in(user_phone, code)

                # Two-step verification may be enabled
                except RPCError as e:
                    if e.password_required:
                        pw = getpass(
                            'Two step verification is enabled. Please enter your password: ')
                        code_ok = self.sign_in(password=pw)
                    else:
                        raise e

    def run(self):
        # Listen for updates
        self.add_update_handler(self.update_handler)

        # Enter a while loop to chat as long as the user wants
        while True:
            # Retrieve the top dialogs
            dialog_count = 10

            # Entities represent the user, chat or channel
            # corresponding to the dialog on the same index
            dialogs, entities = self.get_dialogs(dialog_count)

            i = None
            while i is None:
                try:
                    print_title('Dialogs window')

                    # Display them so the user can choose
                    for i, entity in enumerate(entities):
                        i += 1  # 1-based index for normies
                        print('{}. {}'.format(i, get_display_name(entity)))

                    # Let the user decide who they want to talk to
                    print()
                    print('> Who do you want to send messages to?')
                    print('> Available commands:')
                    print('  !q: Quits the dialogs window and exits.')
                    print('  !l: Logs out, terminating this session.')
                    print()
                    i = input('Enter dialog ID or a command: ')
                    if i == '!q':
                        return
                    if i == '!l':
                        self.log_out()
                        return

                    i = int(i if i else 0) - 1
                    # Ensure it is inside the bounds, otherwise set to None and retry
                    if not 0 <= i < dialog_count:
                        i = None

                except ValueError:
                    pass

            # Retrieve the selected user (or chat, or channel)
            entity = entities[i]
            input_peer = get_input_peer(entity)

            # Show some information
            print_title('Chat with "{}"'.format(get_display_name(entity)))
            print('Available commands:')
            print('  !q: Quits the current chat.')
            print('  !Q: Quits the current chat and exits.')
            print(
                '  !h: prints the latest messages (message History) of the chat.')
            print(
                '  !up <path>: Uploads and sends a Photo located at the given path.')
            print(
                '  !uf <path>: Uploads and sends a File document located at the given path.')
            print(
                '  !dm <msg-id>: Downloads the given message Media (if any).')
            print('  !dp: Downloads the current dialog Profile picture.')
            print()

            # And start a while loop to chat
            while True:
                msg = input('Enter a message: ')
                # Quit
                if msg == '!q':
                    break
                elif msg == '!Q':
                    return

                # History
                elif msg == '!h':
                    # First retrieve the messages and some information
                    total_count, messages, senders = self.get_message_history(
                        input_peer, limit=10)
                    # Iterate over all (in reverse order so the latest appears the last in the console)
                    # and print them in "[hh:mm] Sender: Message" text format
                    for msg, sender in zip(
                            reversed(messages), reversed(senders)):
                        # Get the name of the sender if any
                        name = sender.first_name if sender else '???'

                        # Format the message content
                        if msg.media:
                            self.found_media.add(msg)
                            content = '<{}> {}'.format(  # The media may or may not have a caption
                                msg.media.__class__.__name__,
                                getattr(msg.media, 'caption', ''))
                        else:
                            content = msg.message

                        # And print it to the user
                        print('[{}:{}] (ID={}) {}: {}'.format(
                            msg.date.hour, msg.date.minute, msg.id, name,
                            content))

                # Send photo
                elif msg.startswith('!up '):
                    # Slice the message to get the path
                    self.send_photo(path=msg[len('!p '):], peer=input_peer)

                # Send file (document)
                elif msg.startswith('!uf '):
                    # Slice the message to get the path
                    self.send_document(path=msg[len('!f '):], peer=input_peer)

                # Download media
                elif msg.startswith('!dm '):
                    # Slice the message to get message ID
                    self.download_media(msg[len('!d '):])

                # Download profile photo
                elif msg == '!dp':
                    output = str('usermedia/propic_{}'.format(entity.id))
                    print('Downloading profile picture...')
                    success = self.download_profile_photo(entity.photo, output)
                    if success:
                        print('Profile picture downloaded to {}'.format(
                            output))
                    else:
                        print('"{}" does not seem to have a profile picture.'
                              .format(get_display_name(entity)))

                # Send chat message (if any)
                elif msg:
                    self.send_message(
                        input_peer, msg, markdown=True, no_web_page=True)

    def send_photo(self, path, peer):
        print('Uploading {}...'.format(path))
        input_file = self.upload_file(
            path, progress_callback=self.upload_progress_callback)

        # After we have the handle to the uploaded file, send it to our peer
        self.send_photo_file(input_file, peer)
        print('Photo sent!')

    def send_document(self, path, peer):
        print('Uploading {}...'.format(path))
        input_file = self.upload_file(
            path, progress_callback=self.upload_progress_callback)

        # After we have the handle to the uploaded file, send it to our peer
        self.send_document_file(input_file, peer)
        print('Document sent!')

    def download_media(self, media_id):
        try:
            # The user may have entered a non-integer string!
            msg_media_id = int(media_id)

            # Search the message ID
            for msg in self.found_media:
                if msg.id == msg_media_id:
                    # Let the output be the message ID
                    output = str('usermedia/{}'.format(msg_media_id))
                    print('Downloading media with name {}...'.format(output))
                    output = self.download_msg_media(
                        msg.media,
                        file_path=output,
                        progress_callback=self.download_progress_callback)
                    print('Media downloaded to {}!'.format(output))

        except ValueError:
            print('Invalid media ID given!')

    @staticmethod
    def download_progress_callback(downloaded_bytes, total_bytes):
        InteractiveTelegramClient.print_progress('Downloaded',
                                                 downloaded_bytes, total_bytes)

    @staticmethod
    def upload_progress_callback(uploaded_bytes, total_bytes):
        InteractiveTelegramClient.print_progress('Uploaded', uploaded_bytes,
                                                 total_bytes)

    @staticmethod
    def print_progress(progress_type, downloaded_bytes, total_bytes):
        print('{} {} out of {} ({:.2%})'.format(progress_type, bytes_to_string(
            downloaded_bytes), bytes_to_string(total_bytes), downloaded_bytes /
                                                total_bytes))

    @staticmethod
    def update_handler(update_object):
        if type(update_object) is UpdateShortMessage:
            if update_object.out:
                print('You sent {} to user #{}'.format(update_object.message,
                                                       update_object.user_id))
            else:
                print('[User #{} sent {}]'.format(update_object.user_id,
                                                  update_object.message))

        elif type(update_object) is UpdateShortChatMessage:
            if update_object.out:
                print('You sent {} to chat #{}'.format(update_object.message,
                                                       update_object.chat_id))
            else:
                print('[Chat #{}, user #{} sent {}]'.format(
                    update_object.chat_id, update_object.from_id,
                    update_object.message))
