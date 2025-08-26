import os, zipfile, tempfile, json, sys, time, re, queue, threading, concurrent.futures, shutil, hashlib
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException,
    ElementNotInteractableException
)

# ================== CẤU HÌNH MẶC ĐỊNH ==================
PROXY_HOST = "YOUR PROXY_HOST HERE"
PROXY_PORT = "Your Port Here"
PROXY_USER = "USer Here"
PROXY_PASS = "Pass Here"
SCHEME     = "http"  # mproxy là HTTP

UG_LOGIN_URL = "https://www.ugphone.com/toc-portal/#/login"
SUCCESS_PATH = "/toc-portal/#/inputCode"
LOGIN_PATH   = "/toc-portal/#/login"
CHECK_IP_URL = "https://ipx.ac/"

# API reset IP mproxy (link bạn cung cấp)
MPROXY_RESET_URL = "Your Link Rest IP Here"

# Tốc độ gõ (giây/ký tự)
EMAIL_TYPE_DELAY = 0.06
PASS_TYPE_DELAY  = 0.055
POST_CLICK_PAUSE = 0.5

# Số vòng thử lại login cho mỗi tài khoản (reset → login lại TRONG CÙNG CHROME)
MAX_RETRY_LOGIN = 5
# ============================================================================

# Pool User-Agent xoay theo tài khoản
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]
def pick_user_agent(email: str, idx: int) -> str:
    h = int(hashlib.sha256((email + str(idx)).encode()).hexdigest(), 16)
    return UA_POOL[h % len(UA_POOL)]

def create_proxy_auth_extension_mv3(host, port, user, pwd, scheme="http"):
    manifest = {
        "name": "ProxyAuth MV3 (temp)",
        "version": "1.0.0",
        "manifest_version": 3,
        "permissions": ["proxy", "storage", "webRequest", "webRequestBlocking"],
        "host_permissions": ["<all_urls>"],
        "background": {"service_worker": "sw.js"},
        "minimum_chrome_version": "88.0.0"
    }

    sw_js = f"""
const config = {{
  mode: "fixed_servers",
  rules: {{
    singleProxy: {{
      scheme: "{scheme}",
      host: "{host}",
      port: {int(port)}
    }},
    bypassList: ["localhost","127.0.0.1"]
  }}
}};
chrome.proxy.settings.set({{ value: config, scope: "regular" }}, () => {{}});

function onAuth(details) {{
  return {{
    authCredentials: {{ username: "{user}", password: "{pwd}" }}
  }};
}}
chrome.webRequest.onAuthRequired.addListener(
  onAuth,
  {{ urls: ["<all_urls>"] }},
  ["blocking"]
);
"""
    tmpdir = tempfile.mkdtemp(prefix="mproxy_mv3_")
    mf = os.path.join(tmpdir, "manifest.json")
    sw = os.path.join(tmpdir, "sw.js")
    with open(mf, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(sw, "w", encoding="utf-8") as f:
        f.write(sw_js)

    zip_path = os.path.join(tmpdir, "proxy_auth_mv3.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(mf, "manifest.json")
        z.write(sw, "sw.js")
    return zip_path, tmpdir

def build_driver(use_proxy: bool, proxy_conf: dict, win_w: int, win_h: int,
                 pos_x: int = 0, pos_y: int = 0,
                 user_agent: str = None,
                 user_data_dir: str = None):
    chrome_opts = Options()
    chrome_opts.add_argument("--no-first-run")
    chrome_opts.add_argument("--no-default-browser-check")
    chrome_opts.add_argument("--disable-background-networking")
    chrome_opts.add_argument("--disable-dev-shm-usage")
    chrome_opts.add_argument("--disable-gpu")
    chrome_opts.add_argument("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")
    chrome_opts.add_experimental_option("detach", True)
    chrome_opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_opts.add_experimental_option("useAutomationExtension", False)
    chrome_opts.add_argument(f"--window-size={int(win_w)},{int(win_h)}")
    chrome_opts.add_argument(f"--window-position={int(pos_x)},{int(pos_y)}")

    # Mỗi cửa sổ: profile trắng riêng (tạm)
    if user_data_dir:
        chrome_opts.add_argument(f"--user-data-dir={user_data_dir}")
    chrome_opts.add_argument("--disk-cache-size=1")
    chrome_opts.add_argument("--media-cache-size=1")

    if user_agent:
        chrome_opts.add_argument(f"--user-agent={user_agent}")

    if use_proxy:
        scheme = proxy_conf.get("scheme", "http")
        host   = proxy_conf.get("host", "")
        port   = int(proxy_conf.get("port", 0))
        user   = proxy_conf.get("user", "")
        pwd    = proxy_conf.get("pass", "")
        chrome_opts.add_argument(f"--proxy-server={scheme}://{host}:{port}")
        ext_zip, _tmpdir = create_proxy_auth_extension_mv3(host, port, user, pwd, scheme)
        chrome_opts.add_extension(ext_zip)

    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=chrome_opts)
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        })
    except Exception:
        pass
    return driver

# ========= Helpers =========
def slow_type(element, text, delay=0.25):
    for ch in text:
        element.send_keys(ch)
        time.sleep(delay)

def scroll_into_view(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({behavior:'smooth',block:'center'});", el)
    time.sleep(0.4)

def scroll_to_bottom(driver):
    driver.execute_script("window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'});")
    time.sleep(0.6)

def safe_click(driver, el):
    try:
        scroll_into_view(driver, el)
        el.click()
        time.sleep(POST_CLICK_PAUSE)
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", el)
            time.sleep(POST_CLICK_PAUSE)
            return True
        except Exception:
            return False

def parse_email_pass(line: str):
    if '|' not in line:
        raise ValueError("Sai định dạng. Hãy nhập theo 'email|pass'")
    email, pwd = line.split('|', 1)
    email = email.strip()
    pwd = pwd.strip()
    if not email or not pwd:
        raise ValueError("Thiếu email hoặc mật khẩu.")
    return email, pwd

def first_visible(driver, by, value, timeout=25):
    wait = WebDriverWait(driver, timeout)
    wait.until(EC.presence_of_all_elements_located((by, value)))
    for el in driver.find_elements(by, value):
        try:
            if el.is_displayed() and el.is_enabled():
                return el
        except Exception:
            continue
    return wait.until(EC.visibility_of_element_located((by, value)))

def current_url_safe(driver) -> str:
    try:
        u = driver.current_url
        return u if isinstance(u, str) else ""
    except Exception:
        return ""

# ================== UGPhone click Google ==================
def click_google_button(driver: webdriver.Chrome, timeout=25):
    wait = WebDriverWait(driver, timeout)
    try:
        iframe = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "iframe[src*='accounts.google.com/gsi/button'], iframe[title*='Google'], iframe[title*='Đăng nhập bằng Google'], iframe[title*='Sign in with Google']")))
        driver.switch_to.frame(iframe)
        try:
            btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div[role='button'], button, .nsm7Bb-HzV7m-LgbsSe")))
            safe_click(driver, btn)
        except Exception:
            driver.switch_to.active_element.send_keys(Keys.ENTER)
        driver.switch_to.default_content()
        return True
    except TimeoutException:
        try:
            btn = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button.google-btn, #google-btn, button .btn-content, button.van-button--block")))
            safe_click(driver, btn)
            return True
        except Exception:
            return False

# ================== Google flow ==================
def login_google_flow(driver: webdriver.Chrome, email: str, password: str):
    wait = WebDriverWait(driver, 50)
    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    time.sleep(1.2)
    base_handle = driver.current_window_handle
    for h in driver.window_handles:
        if h != base_handle:
            driver.switch_to.window(h)
            break

    try:
        wait.until(lambda d: ("accounts.google." in (d.current_url or "")) or ("signin" in (d.current_url or "")))
    except TimeoutException:
        return "FedCM/popup: cần thao tác tay."

    # email
    try:
        email_input = first_visible(driver, By.ID, "identifierId", timeout=25)
        scroll_into_view(driver, email_input)
        try: email_input.click()
        except Exception: driver.execute_script("arguments[0].focus();", email_input)
        email_input.clear()
        slow_type(email_input, email, delay=EMAIL_TYPE_DELAY)
        time.sleep(0.25)
        next_btn = first_visible(driver, By.ID, "identifierNext", timeout=15)
        safe_click(driver, next_btn)
    except TimeoutException:
        pass
    except ElementNotInteractableException:
        driver.execute_script("arguments[0].focus();", email_input)
        slow_type(email_input, email, delay=EMAIL_TYPE_DELAY)
        safe_click(driver, first_visible(driver, By.ID, "identifierNext", timeout=15))

    # pass
    wait.until(EC.any_of(
        EC.presence_of_element_located((By.NAME, "Passwd")),
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='Passwd']"))
    ))
    time.sleep(0.3)
    try:
        pwd_input = first_visible(driver, By.CSS_SELECTOR, "input[name='Passwd']", timeout=25)
        scroll_into_view(driver, pwd_input)
        try: pwd_input.click()
        except Exception: driver.execute_script("arguments[0].focus();", pwd_input)
        pwd_input.clear()
        slow_type(pwd_input, password, delay=PASS_TYPE_DELAY)
    except ElementNotInteractableException:
        driver.execute_script("arguments[0].focus(); arguments[0].value='';", pwd_input)
        for ch in password:
            driver.execute_script("arguments[0].value = arguments[0].value + arguments[1];", pwd_input, ch)
            time.sleep(0.03)
    except TimeoutException:
        pass

    # next
    try:
        next_btn2 = first_visible(driver, By.ID, "passwordNext", timeout=20)
        safe_click(driver, next_btn2)
    except Exception:
        pass

    # confirm/continue (nếu có)
    try:
        confirm_btn = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#confirm, input#confirm")))
        scroll_to_bottom(driver); safe_click(driver, confirm_btn)
    except TimeoutException:
        pass
    try:
        cont_btn = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((
            By.XPATH, "//span[normalize-space()='Continue' or normalize-space()='Tiếp tục' or contains(.,'Continue')]")))
        scroll_to_bottom(driver); safe_click(driver, cont_btn)
    except TimeoutException:
        pass

    try:
        WebDriverWait(driver, 120).until(lambda d: "ugphone.com" in (d.current_url or ""))
        return "Đã quay lại UGPhone."
    except TimeoutException:
        return "Chưa quay về UGPhone (có thể cần 2FA/CAPTCHA)."

# ================== Reset IP (mproxy) ==================
def mproxy_reset_ip(log_fn=print):
    """
    Trả về tuple (ok, info, wait_seconds)
    - ok=True: reset thành công
    - ok=False & wait_seconds>0: bị limit 499, cần chờ wait_seconds rồi gọi lại
    - ok=False & wait_seconds=0: lỗi khác
    """
    try:
        r = requests.get(MPROXY_RESET_URL, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log_fn(f"[RESET] Lỗi gọi API: {e}")
        return False, None, 0

    status = data.get("status")
    code   = str(data.get("code"))
    msg    = data.get("message")
    if status == 1 and code in ("1", "200"):
        info = data.get("data", {})
        log_fn(f"[RESET] ✅ Thành công: server={info.get('server')} port={info.get('server_port')}")
        return True, info, 0

    # Bị limit: code 499, có remaining_time
    remaining = 0
    try:
        remaining = int(data.get("data", {}).get("remaining_time", 0))
    except Exception:
        remaining = 0

    if code == "499":
        log_fn(f"[RESET] ⏳ Reset quá nhanh, chờ {remaining}s (msg='{msg}')")
        return False, None, max(remaining, 1)

    log_fn(f"[RESET] ❌ Thất bại: status={status}, code={code}, msg={msg}")
    return False, None, 0

def mproxy_reset_until_success(log_fn=print, max_tries=9999):
    """
    Gọi reset lặp cho tới khi OK:
      - Nếu code 499: chờ đúng remaining_time rồi gọi lại.
      - Nếu lỗi khác: chờ mặc định 3s rồi gọi lại.
    """
    tries = 0
    while tries < max_tries:
        tries += 1
        ok, info, wait_seconds = mproxy_reset_ip(log_fn)
        if ok:
            log_fn(f"[RESET] OK sau {tries} lần thử.")
            return True, info
        time.sleep(wait_seconds if wait_seconds > 0 else 3)
    return False, None

# ================== Auto rotate IP định kỳ (tùy chọn) ==================
def auto_rotate_ip(log_fn=print, interval=61):
    """
    Chạy nền: cứ mỗi 'interval' giây sẽ cố reset IP một lần.
    Nếu bị 499 sẽ tự chờ remaining_time rồi reset tiếp.
    """
    log_fn("== AUTO-RESET: Bắt đầu xoay IP định kỳ ==")
    while True:
        ok, info = mproxy_reset_until_success(log_fn)
        if ok:
            proxy_str = (info or {}).get("proxy")
            log_fn(f"[AUTO-RESET] ✅ Đã đổi IP: {proxy_str}" if proxy_str else "[AUTO-RESET] ✅ Đã đổi IP.")
        time.sleep(interval)

# ================== Worker mỗi account (giữ Chrome, reset rồi login lại TRONG CHROME) ==================
def run_flow_single(ep_line: str, use_proxy: bool, proxy_conf: dict, open_ip_check: bool,
                    win_w: int, win_h: int, pos_x: int, pos_y: int, idx: int, log_fn=print):
    try:
        email, password = parse_email_pass(ep_line)
    except Exception as e:
        log_fn(f"[INPUT] '{ep_line}': {e}")
        return

    # Mỗi account: dựng Chrome 1 lần, profile trắng riêng + UA riêng
    user_data_dir = tempfile.mkdtemp(prefix=f"profile_{re.sub(r'[^a-zA-Z0-9]', '_', email)}_")
    ua = pick_user_agent(email, idx)
    try:
        driver = build_driver(
            use_proxy, proxy_conf, win_w, win_h,
            pos_x=pos_x, pos_y=pos_y,
            user_agent=ua,
            user_data_dir=user_data_dir
        )
    except WebDriverException as e:
        log_fn(f"[Chrome] '{email}': lỗi khởi tạo: {e}")
        shutil.rmtree(user_data_dir, ignore_errors=True)
        return

    try:
        if open_ip_check:
            driver.get(CHECK_IP_URL)
            time.sleep(1.2)

        attempt = 0
        while attempt < MAX_RETRY_LOGIN:
            attempt += 1
            log_fn(f"[{email}] 🔄 Thử đăng nhập (lần {attempt}/{MAX_RETRY_LOGIN}) trong cùng Chrome...")

            driver.get(UG_LOGIN_URL)

            clicked = click_google_button(driver, timeout=25)
            if not clicked:
                log_fn(f"[{email}] ❌ Không nhấn được nút Google.")
                break

            status = login_google_flow(driver, email, password)
            log_fn(f"[{email}] {status}")

            cur_url = current_url_safe(driver)
            if cur_url and (SUCCESS_PATH in cur_url):
                log_fn(f"[{email}] ✅ Thành công: tới trang inputCode.")
                return

            if cur_url and (LOGIN_PATH in cur_url):
                log_fn(f"[{email}] ⚠️ Vẫn ở trang login → SPAM reset IP cho tới khi OK, rồi thử login lại TRONG CHROME HIỆN CÓ.")
                ok, _ = mproxy_reset_until_success(log_fn)
                if not ok:
                    log_fn(f"[{email}] ❌ Reset IP thất bại sau quá nhiều lần. Dừng.")
                    break
                # Reset OK → lặp lại while để login lại trong cùng Chrome
                continue

            log_fn(f"[{email}] ⚠️ URL bất thường: {cur_url or '(rỗng)'}")
            break

    except Exception as e:
        log_fn(f"[{email}] Lỗi luồng: {e}")
    finally:
        # Giữ Chrome mở để thao tác tay. Nếu muốn đóng khi xong:
        # try: driver.quit()
        # except: pass
        # shutil.rmtree(user_data_dir, ignore_errors=True)
        pass

# =========================== UI (Tkinter) ===========================
def start_ui():
    root = tk.Tk()
    root.title("UGPhone Login — Multi-Account + Proxy + Reset mproxy (499-aware) + Keep Chrome + Auto Rotate")
    root.geometry("900x760")

    main = ttk.Frame(root, padding=12); main.pack(fill="both", expand=True)

    # Accounts
    ttk.Label(main, text="Danh sách Email|Pass (mỗi dòng 1 tài khoản):").grid(row=0, column=0, sticky="w")
    accounts_txt = scrolledtext.ScrolledText(main, width=110, height=10)
    accounts_txt.grid(row=1, column=0, columnspan=3, sticky="nsew")
    accounts_txt.insert("1.0", "user1@gmail.com|pass1\nuser2@gmail.com|pass2")

    # Proxy section
    proxy_enable = tk.BooleanVar(value=True)
    ttk.Checkbutton(main, text="Dùng proxy HTTP (mproxy.vn)", variable=proxy_enable)\
        .grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 2))

    left = ttk.Frame(main); mid = ttk.Frame(main); right = ttk.Frame(main)
    left.grid(row=3, column=0, sticky="nsew", padx=(0,8))
    mid.grid(row=3, column=1, sticky="nsew", padx=(0,8))
    right.grid(row=3, column=2, sticky="nsew")

    # left: proxy creds
    ttk.Label(left, text="Proxy host:").grid(row=0, column=0, sticky="w")
    host_var = tk.StringVar(value=PROXY_HOST); ttk.Entry(left, textvariable=host_var, width=28).grid(row=0, column=1, sticky="w")
    ttk.Label(left, text="Proxy port:").grid(row=1, column=0, sticky="w")
    port_var = tk.StringVar(value=str(PROXY_PORT)); ttk.Entry(left, textvariable=port_var, width=28).grid(row=1, column=1, sticky="w")
    ttk.Label(left, text="Proxy user:").grid(row=2, column=0, sticky="w")
    puser_var = tk.StringVar(value=PROXY_USER); ttk.Entry(left, textvariable=puser_var, width=28).grid(row=2, column=1, sticky="w")
    ttk.Label(left, text="Proxy pass:").grid(row=3, column=0, sticky="w")
    ppass_var = tk.StringVar(value=PROXY_PASS); ttk.Entry(left, textvariable=ppass_var, width=28, show="*").grid(row=3, column=1, sticky="w")
    ttk.Label(left, text="Proxy scheme:").grid(row=4, column=0, sticky="w")
    scheme_var = tk.StringVar(value=SCHEME); ttk.Combobox(left, textvariable=scheme_var, values=["http", "https"], width=25, state="readonly").grid(row=4, column=1, sticky="w")

    # mid: concurrency + window + grid + auto rotate
    ttk.Label(mid, text="Số luồng song song:").grid(row=0, column=0, sticky="w")
    threads_var = tk.StringVar(value="3"); ttk.Spinbox(mid, from_=1, to=20, textvariable=threads_var, width=8).grid(row=0, column=1, sticky="w")

    ttk.Label(mid, text="Cỡ cửa sổ (W×H):").grid(row=1, column=0, sticky="w")
    win_w_var = tk.StringVar(value="300"); win_h_var = tk.StringVar(value="250")
    ttk.Entry(mid, textvariable=win_w_var, width=8).grid(row=1, column=1, sticky="w")
    ttk.Entry(mid, textvariable=win_h_var, width=8).grid(row=1, column=2, sticky="w", padx=(6,0))

    ttk.Label(mid, text="Grid margin X/Y:").grid(row=2, column=0, sticky="w")
    margin_x_var = tk.StringVar(value="0"); margin_y_var = tk.StringVar(value="0")
    ttk.Entry(mid, textvariable=margin_x_var, width=8).grid(row=2, column=1, sticky="w")
    ttk.Entry(mid, textvariable=margin_y_var, width=8).grid(row=2, column=2, sticky="w", padx=(6,0))

    ip_check_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(mid, text="Mở ipx.ac trước khi login", variable=ip_check_var).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6,0))

    auto_reset_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(mid, text="Tự động xoay IP mỗi 61s", variable=auto_reset_var).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6,0))

    # right: reset thủ công
    ttk.Label(right, text="Reset IP thủ công:").grid(row=0, column=0, sticky="w")
    def on_reset_now():
        if not proxy_enable.get():
            log_fn("[RESET] Proxy đang tắt -> bỏ qua reset."); return
        ok, _, wait_s = mproxy_reset_ip(log_fn)
        if not ok and wait_s:
            log_fn(f"[RESET] Sẽ tự chờ {wait_s}s rồi thử lại.")
        elif not ok:
            messagebox.showwarning("Reset IP", "Reset thất bại. Xem log để biết chi tiết.")
    ttk.Button(right, text="Reset IP ngay (1 lần)", command=on_reset_now).grid(row=1, column=0, sticky="w", pady=(6,0))

    def on_reset_spam():
        if not proxy_enable.get():
            log_fn("[RESET] Proxy đang tắt -> bỏ qua reset."); return
        threading.Thread(target=lambda: mproxy_reset_until_success(log_fn), daemon=True).start()
    ttk.Button(right, text="Spam reset tới khi OK", command=on_reset_spam).grid(row=2, column=0, sticky="w", pady=(6,0))

    # Log box
    ttk.Label(main, text="Log:").grid(row=4, column=0, sticky="w", pady=(10,0))
    log_box = scrolledtext.ScrolledText(main, width=110, height=14, state="disabled")
    log_box.grid(row=5, column=0, columnspan=3, sticky="nsew")

    # Thread-safe logger
    log_q = queue.Queue()
    def ui_log_pump():
        try:
            while True:
                line = log_q.get_nowait()
                log_box.configure(state="normal")
                log_box.insert("end", line + "\n")
                log_box.see("end")
                log_box.configure(state="disabled")
        except queue.Empty:
            pass
        root.after(100, ui_log_pump)
    def log_fn(msg: str): log_q.put(msg)
    ui_log_pump()

    # Start
    def on_start():
        raw = accounts_txt.get("1.0", "end").strip()
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not lines:
            messagebox.showerror("Thiếu tài khoản", "Dán danh sách email|pass (mỗi dòng 1 tài khoản)."); return

        try: port_int = int(port_var.get().strip())
        except ValueError: messagebox.showerror("Sai cổng", "Proxy port phải là số."); return
        try: n_threads = max(1, min(20, int(threads_var.get().strip())))
        except ValueError: messagebox.showerror("Sai số luồng", "Số luồng phải là số nguyên 1..20."); return
        try:
            win_w = max(400, int(win_w_var.get().strip()))
            win_h = max(300, int(win_h_var.get().strip()))
            margin_x = max(0, int(margin_x_var.get().strip()))
            margin_y = max(0, int(margin_y_var.get().strip()))
        except ValueError:
            messagebox.showerror("Sai kích thước", "Width/Height/Margin phải là số."); return

        proxy_conf = {
            "scheme": scheme_var.get().strip(),
            "host": host_var.get().strip(),
            "port": port_int,
            "user": puser_var.get().strip(),
            "pass": ppass_var.get().strip(),
        }

        # Bật auto rotate nếu tick
        if auto_reset_var.get():
            threading.Thread(target=lambda: auto_rotate_ip(log_fn, interval=61), daemon=True).start()
            log_fn("== AUTO-RESET: Bật chế độ tự động đổi IP mỗi 61 giây ==")

        screen_w = root.winfo_screenwidth()
        cols = max(1, screen_w // (win_w + margin_x))
        log_fn(f"== BẮT ĐẦU: {len(lines)} tài khoản, {n_threads} luồng, window {win_w}x{win_h}, cols={cols}, proxy={'ON' if proxy_enable.get() else 'OFF'} ==")

        def run_pool():
            with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as ex:
                futures = []
                for idx, ln in enumerate(lines):
                    col = idx % cols; row = idx // cols
                    pos_x = col * (win_w + margin_x)
                    pos_y = row * (win_h + margin_y)
                    futures.append(ex.submit(
                        run_flow_single,
                        ln, proxy_enable.get(), proxy_conf, ip_check_var.get(),
                        win_w, win_h, pos_x, pos_y, idx, log_fn
                    ))
                for _ in concurrent.futures.as_completed(futures): pass
            log_fn("== ĐÃ XỬ LÝ XONG TẤT CẢ TÀI KHOẢN ==")

        threading.Thread(target=run_pool, daemon=True).start()

    # Buttons
    btns = ttk.Frame(main); btns.grid(row=6, column=0, columnspan=3, pady=12, sticky="ew")
    ttk.Button(btns, text="Bắt đầu đăng nhập (đa luồng)", command=on_start).pack(side="left")
    ttk.Button(btns, text="Thoát", command=lambda: (root.destroy())).pack(side="right")

    # layout
    main.grid_rowconfigure(1, weight=1)
    main.grid_rowconfigure(5, weight=1)
    main.grid_columnconfigure(0, weight=1)
    main.grid_columnconfigure(1, weight=1)
    main.grid_columnconfigure(2, weight=1)

    hint = (
        "Lưu ý:\n"
        "- Mỗi dòng 1 tài khoản: email|pass\n"
        "- Nếu login vẫn ở #/login: GIỮ Chrome → spam reset IP (tự chờ remaining_time khi code 499) → login lại trong Chrome hiện có.\n"
        "- Mỗi cửa sổ: profile trắng riêng + User-Agent riêng. Có thể bật tự động xoay IP 61s/lần.\n"
        "- Cửa sổ xếp lưới theo kích thước & margin X/Y."
    )
    ttk.Label(main, text=hint, foreground="#555").grid(row=7, column=0, columnspan=3, sticky="w", pady=(6,0))

    root.mainloop()

# =========================== MAIN ===========================
if __name__ == "__main__":
    start_ui()
