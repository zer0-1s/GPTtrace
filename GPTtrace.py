#! /bin/env python3
import argparse
import os
import time

from pathlib import Path
from typing import List, Optional, Tuple

import pygments
from marko.block import FencedCode
from marko.inline import RawText
from marko.parser import Parser
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import PygmentsTokens
from pygments.token import Token
from pygments_markdown_lexer import MarkdownLexer
from revChatGPT.V1 import Chatbot

ENV_UUID = "GPTTRACE_CONV_UUID"
ENV_ACCESS_TOKEN = "GPTTRACE_ACCESS_TOKEN"

PROMPTS_DIR = Path("./prompts")


def pretty_print(input, lexer=MarkdownLexer, *args, **kwargs):
    tokens = list(pygments.lex(input, lexer=lexer()))
    print_formatted_text(PygmentsTokens(tokens), *args, **kwargs)


# print = pretty_print
def main():
    parser = argparse.ArgumentParser(
        prog="GPTtrace",
        description="Use ChatGPT to write eBPF programs (bpftrace, etc.)",
    )

    group = parser.add_mutually_exclusive_group()

    group.add_argument(
        "-i", "--info", help="Let ChatGPT explain what's eBPF", action="store_true"
    )
    group.add_argument(
        "-e",
        "--execute",
        help="Generate commands using your input with ChatGPT, and run it",
        action="store",
        metavar="TEXT",
    )
    group.add_argument(
        "-g", "--generate", help="Generate eBPF programs using your input with ChatGPT", action="store", metavar="TEXT")
    group.add_argument(
        "--train", help="Train ChatGPT with conversions we provided", action="store_true")

    parser.add_argument("-v", "--verbose",
                        help="Show more details", action="store_true")

    parser.add_argument(
        "-u",
        "--uuid",
        help=f"Conversion UUID to use, or passed through environment variable `{ENV_UUID}`",
    )
    parser.add_argument(
        "-t",
        "--access-token",
        help=f"ChatGPT access token, see `https://chat.openai.com/api/auth/session` or passed through `{ENV_ACCESS_TOKEN}`",
    )
    args = parser.parse_args()

    access_token = args.access_token or os.environ.get(ENV_ACCESS_TOKEN, None)
    conv_uuid = args.uuid or os.environ.get(ENV_UUID, None)
    if access_token is None:
        print(
            f"Either provide your access token through `-t` or through environment variable {ENV_ACCESS_TOKEN}"
        )
        return
    chatbot = Chatbot(config={"access_token": access_token})
    if args.info:
        generate_result(chatbot, "Explain what's eBPF", conv_uuid, True)
    elif args.execute is not None:
        desc: str = args.execute
        print("Sending query to ChatGPT: " + desc)
        ret_val, _ = generate_result(
            chatbot, construct_running_prompt(desc), conv_uuid, args.verbose)
        # print(ret_val)
        parsed = make_executable_command(ret_val)
        # print(f"Command to run: {parsed}")
        print("Press Ctrl+C to stop the program....")
        os.system("sudo " + parsed)
    elif args.generate is not None:
        desc: str = args.generate
        print("Sending query to ChatGPT: " + desc)
        ret_val, _ = generate_result(
            chatbot, construct_generate_prompt(desc), conv_uuid)
        pretty_print(ret_val)
        parsed = extract_code_blocks(ret_val)
        # print(f"Command to run: {parsed}")
        with open("generated.bpf.c", "w") as f:
            for code in parsed:
                f.write(code)
    elif args.train:
        prompts = os.listdir(PROMPTS_DIR)
        prompts.sort()
        # conv_uuid could be None, in which we will create a new session and use it in the next steps
        session = conv_uuid
        for file in prompts:
            info = f"Training ChatGPT with `{file}`"
            print("-"*len(info))
            print(info)
            print("-"*len(info))
            with open(PROMPTS_DIR/file, "r") as f:
                input_data = f.read()
            if args.verbose:
                print(input_data)
            resp, session = generate_result(
                chatbot, input_data, conv_uuid, args.verbose)
            time.sleep(2.4)
        print(f"Trained session: {session}")
    else:
        parser.print_help()


def construct_generate_prompt(text: str) -> str:
    return f"""You are now a translater from human language to {os.uname()[0]} eBPF programs.
Please write eBPF programs for me.
No explanation required, no instruction required, don't tell me how to compile and run.
What I want is a eBPF program for: {text}."""


def construct_running_prompt(text: str) -> str:
    return f"""You are now a translater from human language to {os.uname()[0]} shell bpftrace command.
No explanation required.
respond with only the raw shell bpftrace command.
It should be start with `bpftrace`.
Your response should be able to put into a shell and run directly.
Just output in one line, without any description, or any other text that cannot be run in shell.
What should I type to shell to trace using bpftrace for: {text}, in one line."""


def make_executable_command(command: str) -> str:
    if command.startswith("\n"):
        command = command[1:]
    if command.endswith("\n"):
        command = command[:-1]
    if command.startswith("`"):
        command = command[1:]
    if command.endswith("`"):
        command = command[:-1]
    command = command.strip()
    command = command.split("User: ")[0]
    return command


def generate_result(bot: Chatbot, text: str, session: Optional[str] = None, print_out: bool = False) -> Tuple[str, str]:
    from io import StringIO

    prev_text = ""
    buf = StringIO()
    received_session = ""
    for data in bot.ask(
        text, conversation_id=session
    ):
        received_session = data["conversation_id"]
        message = data["message"][len(prev_text):]
        if print_out:
            print(message, end="", flush=True)
        buf.write(message)
        prev_text = data["message"]
    if print_out:
        print()
    return buf.getvalue(), received_session


def extract_code_blocks(text: str) -> List[str]:
    result = []
    parser = Parser()
    for block in parser.parse(text).children:
        if type(block) is FencedCode:
            block: FencedCode
            blk: RawText = block.children[0]
            result.append(blk.children)
    return result


if __name__ == "__main__":
    main()
