import time
import uuid
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import click
import requests
from requests import get
from uuid import uuid4
from re import findall
from requests.exceptions import RequestException
from curl_cffi.requests import get, RequestsError
import g4f
from random import randint
from PIL import Image
import io
import re
import json
import yaml
from webscout.AIutel import Optimizers
from webscout.AIutel import Conversation
from webscout.AIutel import AwesomePrompts, sanitize_stream
from webscout.AIbase import Provider, AsyncProvider
from webscout import exceptions
from typing import Any, AsyncGenerator, Dict
import logging
import httpx

class Julius(Provider):
    AVAILABLE_MODELS = [
        "Llama 3",
        "GPT-4o",
        "GPT-3.5",
        "Command R",
        "Gemini Flash",
        "Gemini 1.5",
    ]
    def __init__(
        self,
        is_conversation: bool = True,
        max_tokens: int = 600,
        timeout: int = 30,
        intro: str = None,
        filepath: str = None,
        update_file: bool = True,
        proxies: dict = {},
        history_offset: int = 10250,
        act: str = None,
        model: str = "Gemini Flash",
    ):
        """Instantiates Julius

        Args:
            is_conversation (bool, optional): Flag for chatting conversationally. Defaults to True.
            max_tokens (int, optional): Maximum number of tokens to be generated upon completion. Defaults to 600.
            timeout (int, optional): Http request timeout. Defaults to 30.
            intro (str, optional): Conversation introductory prompt. Defaults to None.
            filepath (str, optional): Path to file containing conversation history. Defaults to None.
            update_file (bool, optional): Add new prompts and responses to the file. Defaults to True.
            proxies (dict, optional): Http request proxies. Defaults to {}.
            history_offset (int, optional): Limit conversation history to this number of last texts. Defaults to 10250.
            act (str|int, optional): Awesome prompt key or index. (Used as intro). Defaults to None.
            model (str, optional): Model to use for generating text. Defaults to "Gemini Flash". 
                                   Options: "Llama 3", "GPT-4o", "GPT-3.5", "Command R", "Gemini Flash", "Gemini 1.5".
        """
        if model not in self.AVAILABLE_MODELS:
            raise ValueError(f"Invalid model: {model}. Choose from: {self.AVAILABLE_MODELS}")

        self.session = requests.Session()
        self.is_conversation = is_conversation
        self.max_tokens_to_sample = max_tokens
        self.chat_endpoint = "https://api.julius.ai/api/chat/message"
        self.stream_chunk_size = 64
        self.timeout = timeout
        self.last_response = {}
        self.model = model
        self.headers = {
            "accept": "*/*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "en-US,en;q=0.9,en-IN;q=0.8",
            "authorization": "Bearer",
            "content-length": "206",
            "content-type": "application/json",
            "conversation-id": str(uuid.uuid4()),
            "dnt": "1",
            "interactive-charts": "true",
            "is-demo": "temp_14aabbb1-95bc-4203-a678-596258d6fdf3",
            "is-native": "false",
            "orient-split": "true",
            "origin": "https://julius.ai",
            "platform": "undefined",
            "priority": "u=1, i",
            "referer": "https://julius.ai/",
            "request-id": str(uuid.uuid4()),
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0",
            "visitor-id": str(uuid.uuid4())
        }

        self.__available_optimizers = (
            method
            for method in dir(Optimizers)
            if callable(getattr(Optimizers, method)) and not method.startswith("__")
        )
        self.session.headers.update(self.headers)
        Conversation.intro = (
            AwesomePrompts().get_act(
                act, raise_not_found=True, default=None, case_insensitive=True
            )
            if act
            else intro or Conversation.intro
        )
        self.conversation = Conversation(
            is_conversation, self.max_tokens_to_sample, filepath, update_file
        )
        self.conversation.history_offset = history_offset
        self.session.proxies = proxies

    def ask(
        self,
        prompt: str,
        stream: bool = False,
        raw: bool = False,
        optimizer: str = None,
        conversationally: bool = False,
    ) -> dict:
        """Chat with AI

        Args:
            prompt (str): Prompt to be send.
            stream (bool, optional): Whether to stream the response. Defaults to False.
            raw (bool, optional): Whether to return the raw response. Defaults to False.
            optimizer (str, optional): The name of the optimizer to use. Defaults to None.
            conversationally (bool, optional): Whether to chat conversationally. Defaults to False.

        Returns:
            The response from the API.
        """
        conversation_prompt = self.conversation.gen_complete_prompt(prompt)
        if optimizer:
            if optimizer in self.__available_optimizers:
                conversation_prompt = getattr(Optimizers, optimizer)(
                    conversation_prompt if conversationally else prompt
                )
            else:
                raise Exception(
                    f"Optimizer is not one of {self.__available_optimizers}"
                )
        
        payload = {
            "message": {"content": conversation_prompt, "role": "user"},
            "provider": "default",
            "chat_mode": "auto",
            "client_version": "20240130",
            "theme": "dark",
            "new_images": None,
            "new_attachments": None,
            "dataframe_format": "json",
            "selectedModels": [self.model] # Choose the model here
        }

        def for_stream():
            response = self.session.post(
                self.chat_endpoint, json=payload, headers=self.headers, stream=True, timeout=self.timeout
            )

            if not response.ok:
                raise exceptions.FailedToGenerateResponseError(
                    f"Failed to generate response - ({response.status_code}, {response.reason})"
                )
            streaming_response = ""
            for line in response.iter_lines(decode_unicode=True):
                if line:
                    try:
                        json_line = json.loads(line)
                        content = json_line['content']
                        streaming_response += content
                        yield content if raw else dict(text=streaming_response)
                    except:
                        continue
            self.last_response.update(dict(text=streaming_response))
            self.conversation.update_chat_history(
                prompt, self.get_message(self.last_response)
            )

        def for_non_stream():
            response = self.session.post(
                self.chat_endpoint, json=payload, headers=self.headers, timeout=self.timeout
            )

            if not response.ok:
                raise exceptions.FailedToGenerateResponseError(
                    f"Failed to generate response - ({response.status_code}, {response.reason})"
                )
            full_content = ""
            for line in response.text.splitlines():
                try:
                    data = json.loads(line)
                    if "content" in data:
                        full_content += data['content']
                except json.JSONDecodeError:
                    pass
            self.last_response.update(dict(text=full_content))
            self.conversation.update_chat_history(
                prompt, self.get_message(self.last_response)
            )
            return self.last_response

        return for_stream() if stream else for_non_stream()

    def chat(
        self,
        prompt: str,
        stream: bool = False,
        optimizer: str = None,
        conversationally: bool = False,
    ) -> str:
        """Generate response `str`
        Args:
            prompt (str): Prompt to be send.
            stream (bool, optional): Flag for streaming response. Defaults to False.
            optimizer (str, optional): Prompt optimizer name - `[code, shell_command]`. Defaults to None.
            conversationally (bool, optional): Chat conversationally when using optimizer. Defaults to False.
        Returns:
            str: Response generated
        """

        def for_stream():
            for response in self.ask(
                prompt, True, optimizer=optimizer, conversationally=conversationally
            ):
                yield self.get_message(response)

        def for_non_stream():
            return self.get_message(
                self.ask(
                    prompt,
                    False,
                    optimizer=optimizer,
                    conversationally=conversationally,
                )
            )

        return for_stream() if stream else for_non_stream()

    def get_message(self, response: dict) -> str:
        """Retrieves message only from response

        Args:
            response (dict): Response generated by `self.ask`

        Returns:
            str: Message extracted
        """
        assert isinstance(response, dict), "Response should be of dict data-type only"
        return response["text"]
if __name__ == '__main__':
    from rich import print
    ai = Julius()
    response = ai.chat(input(">>> "))
    for chunk in response:
        print(chunk, end="", flush=True)