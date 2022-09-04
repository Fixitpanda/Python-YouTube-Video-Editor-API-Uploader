#!/usr/bin/python

import http.client
import multiprocessing
import random
import time
import httplib2
import moviepy.editor as mpe
from googleapiclient.discovery import build  # noqa
from googleapiclient.errors import HttpError  # noqa
from googleapiclient.http import MediaFileUpload  # noqa
from moviepy.editor import *
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
from termcolor import colored
import threading
import PySimpleGUI as Gui

import videoDetails  # local file

# GUI visual structure interface
Gui.theme('SystemDefault')  # window theme
Gui.set_options(font=("Copper", 11))  # default font

THREAD_EVENT = '-THREAD-'
uploader_account = ['account one', 'account two']


class Tooltips:
    # gui selections / tooltips
    secret_key = 'Place your Google Cloud API key/keys in the folder: your_patch/secret_keys'
    thumbnail = 'Select thumbnail image for YouTube. Can leave empty if you want YouTube generate it automatically'
    main_clip = 'Your main video clip, should be .mp4 format. Other formats was never tested.'
    intro_clip = 'Your into clip, at the begging of the video.'
    outro_clip = 'Your outro clip at the end, such as like subscribe'


selection_layout = [[Gui.Text('Google Secret Key:', tooltip=Tooltips.secret_key),
                     Gui.Combo(uploader_account, tooltip=Tooltips.secret_key, default_value=uploader_account[0],
                               key='board',
                               size=(50, 1))],
                    [Gui.Text('Thumnail (jpg,png,)',
                              tooltip=Tooltips.thumbnail,
                              size=(14, 1)),
                     Gui.InputText(videoDetails.YourEditor.thumbnail_image, tooltip=Tooltips.thumbnail),
                     Gui.FileBrowse()],
                    [Gui.Text('Main Clip (mp4)',
                              tooltip=Tooltips.main_clip,
                              size=(14, 1)), Gui.InputText(videoDetails.YourEditor.raw_video_file), Gui.FileBrowse()],
                    [Gui.Text('Intro Clip (mp4)', tooltip=Tooltips.intro_clip, size=(14, 1)),
                     Gui.InputText(videoDetails.YourEditor.intro_file_location), Gui.FileBrowse()],
                    [Gui.Text('Outro Clip (mp4)', tooltip=Tooltips.outro_clip,
                              size=(14, 1)),
                     Gui.InputText(videoDetails.YourEditor.outro_file_location), Gui.FileBrowse()],
                    ]

buttons_layout = [  # second position argument for button type, cannot use 'center'
    [Gui.Button('Start'), Gui.Button('Clean log', key='Clean'), Gui.Cancel()],
]

layout = [[Gui.Column(selection_layout, element_justification='left', expand_x=True)],
          [Gui.Multiline('  ', size=(75, 10), background_color='black', text_color='White', pad=(5, 5), key='-Main-',
                         autoscroll=True,
                         reroute_stdout=True, write_only=True, )],
          [Gui.Checkbox('Upload to YouTube?', default=True)],
          [Gui.Text('Next cycle timer, shown here.', size=(25, 2), text_color='Blue', pad=(15, 22), key='-Timing-'),
           Gui.Column(buttons_layout, element_justification='right', expand_x=True)]]

# [Gui.Text('Source for Folders', size=(15, 1)), Gui.InputText(), Gui.FolderBrowse()]

# layout = [[Gui.Text('Source for Folders', size=(15, 1)), [Gui.Checkbox('Upload', default=False), Gui.Checkbox('Upload to YouTube?')], Gui.InputText(), Gui.FolderBrowse()], Gui.Text('  ', size=(15, 3), key='Timing')], [Gui.Button('Start'), Gui.Button('Cancel')]
window = Gui.Window(f'Youtube Video Editor API Uploader V2.0, by George Khananaev', layout, size=(600, 460),
                    margins=(5, 5), icon=r'../Media/Images/aliexpress.ico', finalize=True)

# this value overwrites myconfig file. disable if you don't need
# excel_file_location = r'../Media/Data/af_output_ids2.xlsx'

# Explicitly tell the underlying HTTP transport library not to retry, since
# we are handling retry logic ourselves.
httplib2.RETRIES = 1

# Maximum number of times to retry before giving up.
MAX_RETRIES = 10

# Always retry when these exceptions are raised.
RETRIABLE_EXCEPTIONS = (httplib2.HttpLib2Error, IOError, http.client.NotConnected,
                        http.client.IncompleteRead, http.client.ImproperConnectionState,
                        http.client.CannotSendRequest, http.client.CannotSendHeader,
                        http.client.ResponseNotReady, http.client.BadStatusLine)

# Always retry when an apiclient.errors.HttpError with one of these status
# codes is raised.
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]

CLIENT_SECRETS_FILE = './secret_keys/your_client_secrets.json'

SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'

VALID_PRIVACY_STATUSES = ('public', 'private', 'unlisted')


def get_authenticated_service():  # Modified
    credential_path = os.path.join('./secret_keys/credentials/', 'credentials.json')
    store = Storage(credential_path)
    credentials = store.get()
    if not credentials or credentials.invalid:
        flow = client.flow_from_clientsecrets(CLIENT_SECRETS_FILE, SCOPES)
        credentials = tools.run_flow(flow, store)
    return build(API_SERVICE_NAME, API_VERSION, credentials=credentials)


# remove duplicates words in variable
def unique_list(your_values):
    ulist = []
    [ulist.append(x) for x in your_values if x not in ulist]
    return ulist


# youtube upload function
def initialize_upload(youtube, options):  # noqa
    new_youtube_keywords = ' '.join(unique_list(
        videoDetails.Video.title.split()))  # removing duplicates from title, remove function unique_list() if you dont need it.
    new_youtube_title = str(new_youtube_keywords[:100])  # making title up to 100 characters, the rest will be cut off.
    description = str(options.static_description)
    tags = None
    if options.keywords:
        tags = options.keywords.split(',')

    body = dict(
        snippet=dict(
            title=new_youtube_title,
            description=description,
            tags=tags,
            categoryId=options.category
        ),
        status=dict(
            privacyStatus=options.privacyStatus
        )
    )

    # Call the APIs videos.insert method to create and upload the video.
    videoPath = videoDetails.YourEditor.youtube_video_patch + "/%s" % (options.getFileName("video"))
    insert_request = youtube.videos().insert(
        part=','.join(body.keys()),
        body=body,
        media_body=MediaFileUpload(videoPath, chunksize=-1, resumable=True)
    )

    resumable_upload(insert_request, options)


# This method implements an exponential backoff strategy to resume a
# failed upload.
def resumable_upload(request, options):
    response = None
    error = None
    retry = 0
    while response is None:
        try:
            print('Uploading file...')
            status, response = request.next_chunk()
            if response is not None:
                if 'id' in response:
                    print('The video with the id %s was successfully uploaded!' % response['id'])

                    # upload thumbnail for Video
                    options.insertThumbnail(youtube, response['id'])
                else:
                    exit('The upload failed with an unexpected response: %s' % response)
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS_CODES:
                error = 'A retriable HTTP error %d occurred:\n%s' % (e.resp.status,
                                                                     e.content)
            else:
                raise
        except RETRIABLE_EXCEPTIONS as e:
            error = 'A retriable error occurred: %s' % e

        if error is not None:
            print(error)
            retry += 1
            if retry > MAX_RETRIES:
                exit('No longer attempting to retry.')

            max_sleep = 2 ** retry
            sleep_seconds = random.random() * max_sleep
            print('Sleeping %f seconds and then retrying...') % sleep_seconds  # noqa
            time.sleep(sleep_seconds)


if __name__ == '__main__':
    args = videoDetails.Video()
    youtube = get_authenticated_service()

# Calls Google Drive API
google_auth = GoogleAuth()
drive = GoogleDrive(google_auth)

# Grab Current Time Before Running the Code
grab_time_start = time.time()


# clean time output
def sec_to_hours(seconds):
    a = str(seconds // 3600)
    b = str((seconds % 3600) // 60)
    c = str((seconds % 3600) % 60)
    d = "{} hours {} mins {} secs".format(a, b, c)  # noqa
    return d


# Editing VIDEO (Adding Intro, Outro +  LOGO)
def moviepy_video_editor(raw_video_file, video_file_out, logo_file):
    video = mpe.VideoFileClip(raw_video_file, audio=True)  # Source video location and if you want sound output
    w, h = video.size  # This calculating video height and width

    # Intro clip, at the begging
    intro_clip = mpe.VideoFileClip(videoDetails.YourEditor.intro_file_location).resize(width=w)  # noqa

    # Outro clip, at the end of the video
    outro_clip = mpe.VideoFileClip(videoDetails.YourEditor.outro_file_location).resize(width=w)  # noqa

    # Black background for compensation of size differences
    black_background = (mpe.ImageClip(videoDetails.YourEditor.black_image_file)  # Your picture location.
                        .set_duration(outro_clip.duration)
                        .resize((w, h)))

    # Your logo
    logo = (mpe.VideoFileClip(logo_file, has_mask=True)  # noqa # Your picture location.
            .resize(height=50)  # if you need to resize...
            .margin(right=8, top=8, opacity=0.0)  # (optional) logo-border padding
            .set_pos(("right",
                      "bottom")))  # change location of the logo here, simply type, use: "left, right, top, bottom" as values.
    looped_logo = vfx.loop(logo)  # noqa

    intro_resized = mpe.CompositeVideoClip([black_background, intro_clip.set_position("center")]).set_duration(
        intro_clip.duration)
    outro_resized = mpe.CompositeVideoClip([black_background, outro_clip.set_position("center")]).set_duration(
        outro_clip.duration)
    final = mpe.CompositeVideoClip([video, looped_logo]).set_duration(
        video.duration)
    done = concatenate_videoclips([intro_resized, final, outro_resized])
    done.subclip(0, done.duration).write_videofile(video_file_out, fps=60,
                                                   threads=multiprocessing.cpu_count(),
                                                   codec='libx264')
    print(colored('Video editor finished.', 'yellow'))


# function to start the video editing + uploading.
def start_process():
    moviepy_video_editor(videoDetails.YourEditor.raw_video_file, videoDetails.YourEditor.video_file_out,
                         videoDetails.YourEditor.logo_file)  # video editor
    initialize_upload(youtube, args)  # youtube uploader
    grab_time_end = time.time()  # getting end time
    total_time = grab_time_end - grab_time_start  # calculating how many seconds it took
    completed_text = colored('Completed in ', 'yellow')  # output text + color
    print(completed_text,
          sec_to_hours(int(total_time)))  # printing final message and converting seconds to normal hour format


# calling the start function
# start_process()

# GUI, functional loop
while True:
    event, values = window.read()
    start = window['Start']
    # folder_path, file_path = values[0], values[1]
    # check_box = values[2], values[3]
    if event == 'Cancel' or event is None:
        break
    elif event == 'Start':

        print(values)
        # if '  ' == values[0]:
        #     print('''  The file ids can't be empty''')
        # else:
        #     start.update(disabled=True)
        #     window['Delete'].update(disabled=True)
        #     threading.Thread(target=start_process, daemon=False).start()
        # print(create_temporary_upload_directory)
        # print(values[2])
    elif event == 'Delete':
        print('All temporary files deleted.')
    elif event == 'Clean':
        window.FindElement('-Main-').Update('')
    elif event == 'End':
        start.update(disabled=False)

window.close()
