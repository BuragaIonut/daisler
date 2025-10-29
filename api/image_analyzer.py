
import base64

import httpx
from langchain.chat_models import init_chat_model

# Fetch image data
image_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/Gfp-wisconsin-madison-the-nature-boardwalk.jpg/2560px-Gfp-wisconsin-madison-the-nature-boardwalk.jpg"
image_data = base64.b64encode(httpx.get(image_url).content).decode("utf-8")


# Pass to LLM
llm = init_chat_model("anthropic:claude-3-5-sonnet-latest")

message = {
    "role": "user",
    "content": [
        {
            "type": "text",
            "text": "Describe the weather in this image:",
        },
        {
            "type": "image",
            "source_type": "base64",
            "data": image_data,
            "mime_type": "image/jpeg",
        },
    ],
}
response = llm.invoke([message])
print(response.text())