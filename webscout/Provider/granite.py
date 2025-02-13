import requests
import json
from typing import Any, Dict, Generator

from webscout.AIutel import Optimizers, Conversation, AwesomePrompts
from webscout.AIbase import Provider
from webscout import exceptions
from webscout.Litlogger import LitLogger, LogFormat, ColorScheme
from webscout import LitAgent as Lit
class IBMGranite(Provider):
    """
    A class to interact with the IBM Granite API (accessed via d18n68ssusgr7r.cloudfront.net)
    with comprehensive logging and using Lit agent for the user agent.
    """

    AVAILABLE_MODELS = ["granite-3-8b-instruct"]

    def __init__(
        self,
        api_key: str,
        is_conversation: bool = True,
        max_tokens: int = 600,
        timeout: int = 30,
        intro: str = None,
        filepath: str = None,
        update_file: bool = True,
        proxies: dict = {},
        history_offset: int = 10250,
        act: str = None,
        model: str = "granite-3-8b-instruct",
        system_prompt: str = "You are a helpful AI assistant.",
        logging: bool = False
    ):
        """Initializes the IBM Granite API client with logging and Lit agent for the user agent."""
        if model not in self.AVAILABLE_MODELS:
            raise ValueError(f"Invalid model: {model}. Choose from: {self.AVAILABLE_MODELS}")

        # Setup logging if enabled
        self.logger = LitLogger(
            name="IBMGranite",
            format=LogFormat.MODERN_EMOJI,
            color_scheme=ColorScheme.CYBERPUNK
        ) if logging else None

        if self.logger:
            self.logger.info(f"Initializing IBMGranite with model: {model}")

        self.session = requests.Session()
        self.is_conversation = is_conversation
        self.max_tokens_to_sample = max_tokens
        self.api_endpoint = "https://d18n68ssusgr7r.cloudfront.net/v1/chat/completions"
        self.stream_chunk_size = 64
        self.timeout = timeout
        self.last_response = {}
        self.model = model
        self.system_prompt = system_prompt

        # Use Lit agent to generate a random User-Agent
        self.headers = {
            "authority": "d18n68ssusgr7r.cloudfront.net",
            "accept": "application/json,application/jsonl",
            "content-type": "application/json",
            "origin": "https://www.ibm.com",
            "referer": "https://www.ibm.com/",
            "user-agent": Lit().random(),
        }
        self.headers["Authorization"] = f"Bearer {api_key}"
        self.session.headers.update(self.headers)
        self.session.proxies = proxies

        self.__available_optimizers = (
            method for method in dir(Optimizers)
            if callable(getattr(Optimizers, method)) and not method.startswith("__")
        )

        Conversation.intro = (
            AwesomePrompts().get_act(
                act, raise_not_found=True, default=None, case_insensitive=True
            )
            if act
            else intro or Conversation.intro
        )
        self.conversation = Conversation(is_conversation, self.max_tokens_to_sample, filepath, update_file)
        self.conversation.history_offset = history_offset

    def ask(
        self,
        prompt: str,
        stream: bool = False,
        raw: bool = False,
        optimizer: str = None,
        conversationally: bool = False,
    ) -> Dict[str, Any] | Generator[Dict[str, Any], None, None]:
        """Chat with AI
        Args:
            prompt (str): Prompt to be sent.
            stream (bool, optional): Flag for streaming response. Defaults to False.
            raw (bool, optional): Stream back raw response as received. Defaults to False.
            optimizer (str, optional): Prompt optimizer name - `[code, shell_command]`. Defaults to None.
            conversationally (bool, optional): Chat conversationally when using optimizer. Defaults to False.
        Returns:
            Union[Dict, Generator[Dict, None, None]]: Response generated
        """
        if self.logger:
            self.logger.debug(f"Ask method initiated - Prompt (first 50 chars): {prompt[:50]}")

        conversation_prompt = self.conversation.gen_complete_prompt(prompt)
        if optimizer:
            if optimizer in self.__available_optimizers:
                conversation_prompt = getattr(Optimizers, optimizer)(
                    conversation_prompt if conversationally else prompt
                )
                if self.logger:
                    self.logger.debug(f"Applied optimizer: {optimizer}")
            else:
                if self.logger:
                    self.logger.error(f"Invalid optimizer requested: {optimizer}")
                raise Exception(f"Optimizer is not one of {self.__available_optimizers}")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": conversation_prompt},
            ],
            "stream": stream
        }

        def for_stream():
            try:
                if self.logger:
                    self.logger.debug(f"Sending POST request to {self.api_endpoint} with payload: {payload}")
                response = self.session.post(
                    self.api_endpoint, headers=self.headers, json=payload, stream=True, timeout=self.timeout
                )
                if not response.ok:
                    msg = f"Request failed with status code {response.status_code}: {response.text}"
                    if self.logger:
                        self.logger.error(msg)
                    raise exceptions.FailedToGenerateResponseError(msg)

                streaming_text = ""
                for line in response.iter_lines(decode_unicode=True):
                    if line:
                        try:
                            data = json.loads(line)
                            if len(data) == 2 and data[0] == 3 and isinstance(data[1], str):
                                content = data[1]
                                streaming_text += content
                                yield content if raw else dict(text=content)
                            else:
                                if self.logger:
                                    self.logger.debug(f"Skipping unrecognized line: {line}")
                        except json.JSONDecodeError as e:
                            if self.logger:
                                self.logger.error(f"JSON decode error: {e}")
                            continue
                self.last_response.update(dict(text=streaming_text))
                self.conversation.update_chat_history(prompt, self.get_message(self.last_response))
                if self.logger:
                    self.logger.info("Stream processing completed.")

            except requests.exceptions.RequestException as e:
                if self.logger:
                    self.logger.error(f"Request exception: {e}")
                raise exceptions.ProviderConnectionError(f"Request failed: {e}")
            except json.JSONDecodeError as e:
                if self.logger:
                    self.logger.error(f"Invalid JSON received: {e}")
                raise exceptions.InvalidResponseError(f"Failed to decode JSON response: {e}")
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Unexpected error: {e}")
                raise exceptions.FailedToGenerateResponseError(f"An unexpected error occurred: {e}")

        def for_non_stream():
            # Run the generator to completion
            for _ in for_stream():
                pass
            return self.last_response

        return for_stream() if stream else for_non_stream()

    def chat(
        self,
        prompt: str,
        stream: bool = False,
        optimizer: str = None,
        conversationally: bool = False,
    ) -> str | Generator[str, None, None]:
        """Generate response as a string using chat method"""
        if self.logger:
            self.logger.debug(f"Chat method initiated - Prompt (first 50 chars): {prompt[:50]}")

        def for_stream():
            for response in self.ask(prompt, True, optimizer=optimizer, conversationally=conversationally):
                yield self.get_message(response)

        def for_non_stream():
            result = self.get_message(
                self.ask(prompt, False, optimizer=optimizer, conversationally=conversationally)
            )
            if self.logger:
                self.logger.info("Chat method completed.")
            return result

        return for_stream() if stream else for_non_stream()

    def get_message(self, response: dict) -> str:
        """Retrieves message only from response"""
        assert isinstance(response, dict), "Response should be of dict data-type only"
        return response["text"]

if __name__ == "__main__":
    from rich import print
    # Example usage: Initialize with logging enabled.
    ai = IBMGranite(
        api_key="", # press f12 to see the API key
        logging=True
    )
    response = ai.chat("write a poem about AI", stream=True)
    for chunk in response:
        print(chunk, end="", flush=True)