## Jupyter Clickable Stream Widget

This repository contains a clickable image widget just like [jupyter_clickable_image_widget](https://github.com/jaybdub/jupyter_clickable_image_widget) but it uses WebRTC to reduce network traffic when updating the image.

This widget will execute the callback function with the clicked location when image is clicked.

### Install

Run the following commands in your terminal.

```bash
cd ~
git clone https://github.com/LeeChunHei/jupyter_clickable_stream_widget.git
cd jupyter_clickable_stream_widget
sudo -H python3 setup.py install
```

### Example

You can run the [example.ipynb](https://github.com/LeeChunHei/jupyter_clickable_stream_widget/blob/main/example.ipynb) Jupyter notebook script on your JetRacer or JetBot JupyterLab environment to test this widget.

Here is a code snippet about how to update the image and receive clicked location.

```python
from clickable_stream_widget.widget import ClickableImageWidget
from IPython.display import display

stream_widget = ClickableImageWidget(width=224, height=224, encoder="omxvp8enc") # create a stream widget with omxvp8enc encoder, default using vp8enc

def on_clicked(_, content, msg):
    '''
    stream widget callback function
    '''
    if content['event'] == 'click':
        data = content['eventData']
        x = data['offsetX']
        y = data['offsetY']
        # do something ...

stream_widget.on_msg(on_clicked)    # register the callback function
display(stream_widget)              # display the stream widget

while True:
    img = ...                   # get the display image
    stream_widget.data = img    # supply an image frame to stream widget

# This widget also support traitlets.dlink
import traitlets

traitlets.dlink((img_src, 'value'), (stream_widget, 'data'))
img_src.running = True
```