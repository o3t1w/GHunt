#!/usr/bin/env python3

from lib import modwall; modwall.check() # We check the requirements

import json
from time import time
import os
from os.path import isfile
from pathlib import Path
from ssl import SSLError
import base64
from copy import deepcopy

import httpx
from seleniumwire import webdriver
from selenium.common.exceptions import TimeoutException as SE_TimeoutExepction
from bs4 import BeautifulSoup as bs

import config
from lib.utils import *
from lib import listener


# We change the current working directory to allow using GHunt from anywhere
os.chdir(Path(__file__).parents[0])

def get_saved_cookies():
    ''' Returns cookie cache if exists '''
    if isfile(config.data_path):
        try:
            with open(config.data_path, 'r') as f:
                out = json.loads(f.read())
                cookies = out["cookies"]
                print("[+] Detected stored cookies, checking it")
                return cookies
        except Exception:
            print("[-] Stored cookies are corrupted\n")
            return False
    print("[-] No stored cookies found\n")
    return False


def get_authorization_source(driver):
    ''' Returns html source of docs page
        if user authorized
    '''
    driver.get('https://docs.google.com/document/u/0/')
    if "myaccount.google.com" in driver.page_source:
            return driver.page_source
    return None


def save_tokens(gdoc_token, chat_key, chat_auth, internal_token, internal_auth, cac_key, cookies, osid):
    '''Ssave tokens to file '''
    output = {
        "chat_auth": chat_auth, "internal_auth": internal_auth,
        "keys": {"gdoc": gdoc_token, "chat": chat_key, "internal": internal_token, "clientauthconfig": cac_key},
        "cookies": cookies,
        "osids": {
            "cloudconsole": osid
        }
    }
    with open(config.data_path, 'w') as f:
        f.write(json.dumps(output))


def get_chat_tokens(cookies):
    """ Return the API key used by Google Chat for
        Internal People API and a generated SAPISID hash."""

    chat_key = "AIzaSyB0RaagJhe9JF2mKDpMml645yslHfLI8iA"
    chat_auth = f"SAPISIDHASH {gen_sapisidhash(cookies['SAPISID'], 'https://chat.google.com')}"

    return (chat_key, chat_auth)

def get_people_tokens(cookies):
    """ Return the API key used by Drive for
        Internal People API and a generated SAPISID hash."""

    people_key = "AIzaSyAy9VVXHSpS2IJpptzYtGbLP3-3_l0aBk4"
    people_auth = f"SAPISIDHASH {gen_sapisidhash(cookies['SAPISID'], 'https://drive.google.com')}"

    return (people_key, people_auth)

def gen_osid(cookies, domain, service):
    req = httpx.get(f"https://accounts.google.com/ServiceLogin?service={service}&osid=1&continue=https://{domain}/&followup=https://{domain}/&authuser=0",
                    cookies=cookies, headers=config.headers)

    body = bs(req.text, 'html.parser')
    
    params = {x.attrs["name"]:x.attrs["value"] for x in body.find_all("input", {"type":"hidden"})}

    headers = {**config.headers, **{"Content-Type": "application/x-www-form-urlencoded"}}
    req = httpx.post(f"https://{domain}/accounts/SetOSID", cookies=cookies, data=params, headers=headers)

    osid_header = [x for x in req.headers["set-cookie"].split(", ") if x.startswith("OSID")]
    if not osid_header:
        exit("[-] No OSID header detected, exiting...")

    osid = osid_header[0].split("OSID=")[1].split(";")[0]
    
    return osid

def get_clientauthconfig_key(cookies):
    """ Extract the Client Auth Config API token."""

    req = httpx.get("https://console.cloud.google.com",
                    cookies=cookies, headers=config.headers)

    if req.status_code == 200 and "pantheon_apiKey" in req.text:
        cac_key = req.text.split('pantheon_apiKey\\x22:')[1].split(",")[0].strip('\\x22')
        return cac_key
    exit("[-] I can't find the Client Auth Config API...")

def check_cookies(cookies):
    wanted = ["authuser", "continue", "osidt", "ifkv"]

    req = httpx.get(f"https://accounts.google.com/ServiceLogin?service=cloudconsole&osid=1&continue=https://console.cloud.google.com/&followup=https://console.cloud.google.com/&authuser=0",
                    cookies=cookies, headers=config.headers)

    body = bs(req.text, 'html.parser')
    
    params = [x.attrs["name"] for x in body.find_all("input", {"type":"hidden"})]
    for param in wanted:
        if param not in params:
            return False

    return True

def getting_cookies(cookies):
    choices = ("You can facilitate configuring GHunt by using the GHunt Companion extension on Firefox, Chrome, Edge and Opera here :\n"
                "=> https://github.com/mxrch/ghunt_companion\n\n"
                "[1] (Companion) Put GHunt on listening mode (currently not compatible with docker)\n"
                "[2] (Companion) Paste base64-encoded cookies\n"
                "[3] Enter manually all cookies\n\n"
                "Choice => ")

    choice = input(choices)
    if choice not in ["1","2","3"]:
        exit("Please choose a valid choice. Exiting...")

    if choice == "1":
        received_cookies = listener.run()
        cookies = json.loads(base64.b64decode(received_cookies))

    elif choice == "2":
        received_cookies = input("Paste the cookies here => ")
        cookies = json.loads(base64.b64decode(received_cookies))

    elif choice == "3":
        for name in cookies.keys():
            if not cookies[name]:
                cookies[name] = input(f"{name} => ").strip().strip('\"')

    return cookies

def get_driver(cookies = {}):
    driverpath = get_driverpath()
    
    chrome_options = get_chrome_options_args(config.headless)
    options = {
        'connection_timeout': None  # Never timeout, otherwise it floods errors
    }

    tmprinter.out("Starting browser...")
    driver = webdriver.Chrome(
        executable_path=driverpath, seleniumwire_options=options,
        options=chrome_options
    )
    driver.header_overrides = config.headers
    driver.get('https://www.google.com/robots.txt')
    for k, v in cookies.items():
        driver.add_cookie({'name': k, 'value': v, 'domain': '.google.com'})
    return driver

if __name__ == '__main__':

    driver = None

    cookies_from_file = get_saved_cookies()

    tmprinter = TMPrinter()

    cookies = {"SID": "", "SSID": "", "APISID": "", "SAPISID": "", "HSID": "", "LSID": "", "__Secure-3PSID": "", "CONSENT": config.default_consent_cookie, "PREF": config.default_pref_cookie}

    new_cookies_entered = False

    if not cookies_from_file:
        cookies = getting_cookies(cookies)
        new_cookies_entered = True
    else:
        # in case user wants to enter new cookies (example: for new account)
        driver = get_driver(cookies_from_file)
        html = get_authorization_source(driver)
        valid_cookies = check_cookies(cookies_from_file)
        valid = False
        if html and valid_cookies:
            print("[+] The cookies seems valid !")
            valid = True
        else:
            print("[-] Seems like the cookies are invalid.")
        new_gen_inp = input("\nDo you want to enter new browser cookies from accounts.google.com ? (Y/n) ").lower()
        if new_gen_inp in ["y", ""]:
            cookies = getting_cookies(cookies)
            new_cookies_entered = True
            
        elif not valid:
            exit("Please put valid cookies. Exiting...")
    
    if not driver:
        driver = get_driver(cookies)

    # Validate cookies
    if new_cookies_entered or not cookies_from_file:
        html = get_authorization_source(driver)
        if html:
            print("\n[+] The cookies seems valid !")
        else:
            exit("\n[-] Seems like the cookies are invalid, try regenerating them.")
    
    if not new_cookies_entered:
        cookies = cookies_from_file
        choice = input("Do you want to generate new tokens ? (Y/n) ").lower()
        if choice not in ["y", ""]:
            exit()

    # Start the extraction process

    print("Extracting the tokens...\n")
    # Extracting Google Docs token
    trigger = '\"token\":\"'
    if trigger not in html:
        exit("[-] I can't find the Google Docs token in the source code...\n")
    else:
        gdoc_token = html.split(trigger)[1][:100].split('"')[0]
        print("Google Docs Token => {}".format(gdoc_token))

    print("Generating OSID for the Cloud Console...")
    osid = gen_osid(cookies, "console.cloud.google.com", "cloudconsole")
    cookies_with_osid = deepcopy(cookies)
    cookies_with_osid["OSID"] = osid
    # Extracting Internal People API tokens
    people_key, people_auth = get_people_tokens(cookies_with_osid)
    print(f"People API Key => {people_key}")
    print(f"People API Auth => {people_auth}")


    # Extracting Chat tokens
    chat_key, chat_auth = get_chat_tokens(cookies_with_osid)
    print(f"Chat Key => {chat_key}")
    print(f"Chat Auth => {chat_auth}")

    cac_key = get_clientauthconfig_key(cookies_with_osid)
    print(f"Client Auth Config API Key => {cac_key}")

    save_tokens(gdoc_token, chat_key, chat_auth, people_key, people_auth, cac_key, cookies, osid)
