#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import pickle
import random
import re
import time
from pathlib import Path
from typing import Iterable, List, Optional, Set, Dict, Tuple
from urllib.parse import quote_plus

import chromedriver_autoinstaller
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# selenium-wire để hỗ trợ proxy có username/password
try:
    from seleniumwire import webdriver as wire_webdriver  # type: ignore
except ImportError:
    wire_webdriver = None

# Regex khớp URL CDN Pinterest. Lưu ý: chỉ cần một backslash escape cho dấu chấm.
PIN_IMG_PATTERN = re.compile(r"pinimg\.com")

# File để lưu proxy key
PROXY_KEY_FILE = Path(".proxy_key")


def load_proxy_key() -> Optional[str]:
    """
    Đọc proxy key từ file .proxy_key hoặc environment variable PROXY_KEY.
    Thứ tự ưu tiên: Environment variable > File .proxy_key
    """
    # Kiểm tra environment variable trước
    proxy_key = os.getenv("PROXY_KEY")
    if proxy_key:
        return proxy_key.strip()
    
    # Kiểm tra file .proxy_key
    if PROXY_KEY_FILE.exists():
        try:
            with open(PROXY_KEY_FILE, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    return key
        except Exception as e:
            print(f"[PROXY] Cảnh báo: Không thể đọc file .proxy_key: {e}")
    
    return None


def save_proxy_key(proxy_key: str) -> bool:
    """
    Lưu proxy key vào file .proxy_key
    """
    try:
        with open(PROXY_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(proxy_key.strip())
        # Đặt quyền file để bảo mật (chỉ owner đọc được)
        os.chmod(PROXY_KEY_FILE, 0o600)
        return True
    except Exception as e:
        print(f"[PROXY] Cảnh báo: Không thể lưu proxy key: {e}")
        return False


def get_proxy_from_ckey(keyproxy: str, nhamang: str = "Random", tinhthanh: str = "0", whitelist: str = "") -> Optional[Dict[str, str]]:
    """
    Lấy proxy từ API ckey.vn
    
    Args:
        keyproxy: Key proxy từ ckey.vn
        nhamang: Random, Viettel, Vinaphone, fpt
        tinhthanh: 0=Random, 1=Phú Thọ, 2=Tuyên quang, 3=Hà Nội, ...
        whitelist: IP whitelist (tùy chọn)
    
    Returns:
        Dict chứa thông tin proxy hoặc None nếu lỗi
        Format: {
            "proxyhttp": "host:port:username:password",
            "proxysocks5": "host:port:username:password",
            "host": "host",
            "port": "port",
            "username": "username",
            "password": "password"
        }
    """
    try:
        url = "https://ckey.vn/api/getproxyxoay"
        params = {
            "keyproxy": keyproxy,
            "nhamang": nhamang,
            "tinhthanh": tinhthanh
        }
        if whitelist:
            params["whitelist"] = whitelist
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == 100:
            proxyhttp = data.get("proxyhttp", "")
            if proxyhttp:
                # Parse format: "host:port:username:password"
                parts = proxyhttp.split(":")
                if len(parts) >= 4:
                    host = parts[0]
                    port = parts[1]
                    username = parts[2]
                    password = ":".join(parts[3:])  # Password có thể chứa ":"
                    
                    return {
                        "proxyhttp": proxyhttp,
                        "proxysocks5": data.get("proxysocks5", ""),
                        "host": host,
                        "port": port,
                        "username": username,
                        "password": password,
                        "nhamang": data.get("Nha Mang", ""),
                        "vitri": data.get("Vi Tri", ""),
                        "expires": data.get("Token expiration date", "")
                    }
        print(f"[PROXY] Lỗi lấy proxy: {data.get('message', 'Unknown error')}")
        return None
    except Exception as e:
        print(f"[PROXY] Lỗi khi gọi API proxy: {e}")
        return None


def parse_proxy_string(proxy_string: str) -> Optional[Dict[str, str]]:
    """
    Parse chuỗi proxy từ format "host:port:username:password"
    """
    try:
        parts = proxy_string.split(":")
        if len(parts) >= 4:
            host = parts[0]
            port = parts[1]
            username = parts[2]
            password = ":".join(parts[3:])
            return {
                "host": host,
                "port": port,
                "username": username,
                "password": password
            }
    except Exception as e:
        print(f"[PROXY] Lỗi parse proxy string: {e}")
    return None


def to_original_url(url: str) -> str:
    """
    Chuyển URL thumbnail về URL ảnh gốc (originals) nếu có thể.
    Ví dụ: /60x60/, /75x75_RS/, /236x/, /474x/, /736x/ -> /originals/
    """
    # Bỏ query string để tránh lặp tham số
    base, *rest = url.split("?", 1)
    # Thay các pattern kích thước phổ biến
    base = (
        base.replace("/75x75_RS/", "/originals/")
        .replace("/60x60/", "/originals/")
        .replace("/236x/", "/originals/")
        .replace("/474x/", "/originals/")
        .replace("/736x/", "/originals/")
    )
    # Nếu vẫn có pattern dạng /<số>x<số>/ thì cũng đưa về originals
    base = re.sub(r"/\d+x\d+/", "/originals/", base)
    # Gắn lại query nếu cần
    return base + ("" if not rest else "?" + rest[0])


class InfinitePinterestCrawler:
    """
    Bắt chước cách repo chính cuộn vô hạn: dùng Selenium, gom ảnh mới sau mỗi lần cuộn.
    """

    def __init__(
        self, 
        headless: bool = False, 
        cookies_path: str = "cookies.pkl",
        proxy_key: Optional[str] = None,
        proxy_nhamang: str = "Random",
        proxy_tinhthanh: str = "0",
        proxy_rotate_after: int = 50  # Rotate proxy sau mỗi N lần scroll
    ) -> None:
        print("[MAIN] Bắt đầu khởi tạo ChromeDriver...")
        import time
        import threading
        
        # Chạy chromedriver_autoinstaller trong thread với timeout
        install_done = threading.Event()
        install_error = [None]
        
        def install_chromedriver():
            try:
                chromedriver_autoinstaller.install()
                install_done.set()
            except Exception as e:
                install_error[0] = e
                install_done.set()
        
        start = time.time()
        thread = threading.Thread(target=install_chromedriver, daemon=True)
        thread.start()
        
        # Đợi tối đa 30 giây
        if install_done.wait(timeout=30):
            elapsed = time.time() - start
            if install_error[0]:
                print(f"[MAIN] Lỗi khi cài ChromeDriver sau {elapsed:.2f}s: {install_error[0]}")
                raise install_error[0]
            print(f"[MAIN] Đã chuẩn bị ChromeDriver xong (mất {elapsed:.2f}s)")
        else:
            elapsed = time.time() - start
            print(f"[MAIN] Cảnh báo: ChromeDriver install đang mất quá nhiều thời gian ({elapsed:.2f}s), tiếp tục...")
            # Tiếp tục dù chưa install xong, có thể đã có sẵn
        self.proxy_key = proxy_key
        self.proxy_nhamang = proxy_nhamang
        self.proxy_tinhthanh = proxy_tinhthanh
        self.proxy_rotate_after = proxy_rotate_after
        self.proxy_info: Optional[Dict[str, str]] = None
        self.scroll_count = 0
        self.headless = headless
        self.use_seleniumwire = bool(proxy_key and wire_webdriver is not None)
        
        print(f"[PROXY] Đang khởi tạo driver... (use_seleniumwire={self.use_seleniumwire})")
        options, wire_options = self._create_chrome_options(headless)
        
        if self.use_seleniumwire:
            try:
                print("[PROXY] Đang khởi tạo driver với selenium-wire...")
                print(f"[PROXY] Wire options: {wire_options}")
                import time
                start_time = time.time()
                self.driver = wire_webdriver.Chrome(  # type: ignore
                    options=options,
                    seleniumwire_options=wire_options,
                )
                elapsed = time.time() - start_time
                print(f"[PROXY] Đã khởi tạo driver với selenium-wire thành công (mất {elapsed:.2f}s)")
            except Exception as e:
                print(f"[PROXY] Lỗi khởi tạo driver với selenium-wire: {e}")
                print("[PROXY] Thử khởi tạo driver không proxy")
                options = webdriver.ChromeOptions()
                if headless:
                    options.add_argument("headless")
                options.add_argument("window-size=1920x1080")
                options.add_argument("disable-gpu")
                options.add_argument("--log-level=3")
                self.driver = webdriver.Chrome(options=options)
                self.use_seleniumwire = False
        else:
            if proxy_key and wire_webdriver is None:
                print("[PROXY] Cảnh báo: Chưa cài selenium-wire, proxy có auth sẽ không hoạt động. Cài: pip install selenium-wire")
            print("[PROXY] Đang khởi tạo driver không proxy...")
            self.driver = webdriver.Chrome(options=options)
        
        self.seen: Set[str] = set()
        self.cookies_path = cookies_path
        # Mở trang chính trước khi add cookie
        print("[PROXY] Đang mở Pinterest...")
        max_retries = 3
        for retry in range(max_retries):
            try:
                self.driver.get("https://www.pinterest.com")
                self.driver.implicitly_wait(3)
                # Kiểm tra xem có load được không
                if "pinterest" in self.driver.current_url.lower() or len(self.driver.page_source) > 1000:
                    print("[PROXY] Đã mở Pinterest thành công")
                    break
                else:
                    raise Exception("Trang không load đúng")
            except Exception as e:
                if retry < max_retries - 1:
                    print(f"[PROXY] Lỗi kết nối (lần thử {retry + 1}/{max_retries}): {e}")
                    if self.proxy_key and self.use_seleniumwire:
                        print("[PROXY] Đang thử rotate proxy mới...")
                        if self.rotate_proxy():
                            continue
                    print("[PROXY] Thử lại sau 2 giây...")
                    time.sleep(2)
                else:
                    print(f"[PROXY] Không thể kết nối sau {max_retries} lần thử")
                    if self.proxy_key:
                        print("[PROXY] Cảnh báo: Proxy có vẻ không hoạt động. Có thể proxy đã hết hạn hoặc bị chặn.")
                    raise
        
        self._load_cookies_if_any()
        # reload sau khi set cookie để Pinterest nhận session
        try:
            self.driver.get("https://www.pinterest.com")
            self.driver.implicitly_wait(3)
        except Exception as e:
            print(f"[PROXY] Cảnh báo khi reload Pinterest: {e}")
    
    def _create_chrome_options(self, headless: bool) -> Tuple[webdriver.ChromeOptions, Dict]:
        """Tạo Chrome options với proxy nếu có"""
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument("headless")
        options.add_argument("window-size=1920x1080")
        options.add_argument("disable-gpu")
        options.add_argument("--log-level=3")
        
        wire_options = {}
        
        # Cấu hình proxy nếu có
        if self.proxy_key:
            print(f"[PROXY] Đang lấy proxy từ ckey.vn... (key={self.proxy_key[:10]}...)")
            try:
                proxy_info = get_proxy_from_ckey(
                    keyproxy=self.proxy_key,
                    nhamang=self.proxy_nhamang,
                    tinhthanh=self.proxy_tinhthanh
                )
            except Exception as e:
                print(f"[PROXY] Exception khi lấy proxy: {e}")
                import traceback
                traceback.print_exc()
                proxy_info = None
            
            if proxy_info:
                self.proxy_info = proxy_info
                has_auth = bool(proxy_info.get("username") or proxy_info.get("password"))
                host_port = f"{proxy_info['host']}:{proxy_info['port']}"
                http_proxy = (
                    f"http://{proxy_info['username']}:{proxy_info['password']}@{host_port}"
                    if has_auth else f"http://{host_port}"
                )
                if self.use_seleniumwire:
                    # Dùng selenium-wire với proxy có auth
                    wire_options = {
                        'proxy': {
                            'http': http_proxy,
                            'https': http_proxy,
                            'no_proxy': 'localhost,127.0.0.1'
                        }
                    }
                    print(f"[PROXY] Đã cấu hình proxy với selenium-wire: {host_port} ({proxy_info.get('nhamang', 'Unknown')} - {proxy_info.get('vitri', 'Unknown')}) | Auth: {has_auth}")
                else:
                    # Dùng Chrome options (không hỗ trợ auth tốt)
                    proxy_url = http_proxy
                    options.add_argument(f"--proxy-server={proxy_url}")
                    print(f"[PROXY] Đã cấu hình proxy: {host_port} ({proxy_info.get('nhamang', 'Unknown')} - {proxy_info.get('vitri', 'Unknown')}) | Auth: {has_auth}")
                print(f"[PROXY] Proxy hết hạn: {proxy_info.get('expires', 'Unknown')}")
            else:
                print("[PROXY] Cảnh báo: Không thể lấy proxy, tiếp tục không dùng proxy")
        
        return options, wire_options
    
    def rotate_proxy(self) -> bool:
        """Rotate proxy mới"""
        if not self.proxy_key:
            return False
        
        try:
            print("[PROXY] Đang rotate proxy mới...")
            # Đóng driver cũ
            self.driver.quit()
            
            # Lấy proxy mới
            proxy_info = get_proxy_from_ckey(
                keyproxy=self.proxy_key,
                nhamang=self.proxy_nhamang,
                tinhthanh=self.proxy_tinhthanh
            )
            
            if proxy_info:
                self.proxy_info = proxy_info
                # Tạo driver mới với proxy mới (giữ nguyên headless state)
                options, wire_options = self._create_chrome_options(self.headless)
                if self.use_seleniumwire:
                    self.driver = wire_webdriver.Chrome(  # type: ignore
                        options=options,
                        seleniumwire_options=wire_options,
                    )
                else:
                    self.driver = webdriver.Chrome(options=options)
                self.driver.get("https://www.pinterest.com")
                self.driver.implicitly_wait(3)
                self._load_cookies_if_any()
                self.driver.get("https://www.pinterest.com")
                self.driver.implicitly_wait(3)
                print(f"[PROXY] Đã rotate sang proxy mới: {proxy_info['host']}:{proxy_info['port']}")
                self.scroll_count = 0  # Reset counter
                return True
            else:
                print("[PROXY] Không thể lấy proxy mới, tiếp tục với proxy cũ")
                return False
        except Exception as e:
            print(f"[PROXY] Lỗi khi rotate proxy: {e}")
            return False

    def _load_cookies_if_any(self) -> None:
        if not self.cookies_path or not os.path.exists(self.cookies_path):
            return
        try:
            cookies = pickle.load(open(self.cookies_path, "rb"))
        except Exception:
            return
        for cookie in cookies:
            try:
                self.driver.add_cookie(cookie)
            except WebDriverException:
                # Bỏ qua cookie nào không hợp lệ cho domain hiện tại
                pass

    def _save_cookies(self) -> None:
        if not self.cookies_path:
            return
        try:
            cookies = self.driver.get_cookies()
            pickle.dump(cookies, open(self.cookies_path, "wb"))
        except Exception:
            pass

    def is_logged_in(self) -> bool:
        """Kiểm tra nhanh xem đã vào giao diện sau khi login hay chưa."""
        try:
            self.driver.find_element(By.XPATH, '//*[@id="HeaderContent"]')
            return True
        except Exception:
            return False

    def login(self, email: str, password: str, debug: bool = False) -> bool:
        """Đăng nhập bằng email/password, trả về True nếu thành công."""
        if not email or not password:
            return False
        self.driver.get("https://www.pinterest.com/login")
        self.driver.implicitly_wait(3)
        try:
            email_elem = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "email"))
            )
            pass_elem = self.driver.find_element(By.ID, "password")
            email_elem.clear()
            pass_elem.clear()
            email_elem.send_keys(email)
            pass_elem.send_keys(password)
            submit_btn = self.driver.find_element(By.XPATH, "//button[@type='submit']")
            submit_btn.click()
        except Exception as e:
            if debug:
                print(f"[DEBUG] Không tìm thấy form login: {e}")
            return False

        # Đợi header xuất hiện để xác nhận login
        ok = False
        for _ in range(12):
            try:
                self.driver.find_element(By.XPATH, '//*[@id="HeaderContent"]')
                ok = True
                break
            except Exception:
                time.sleep(1)
        if debug and not ok:
            print("[DEBUG] Login chưa xác nhận được header.")
        if ok:
            self._save_cookies()
        return ok

    def open_search(self, keyword: str) -> None:
        url = f"https://www.pinterest.com/search/pins/?q={quote_plus(keyword)}&rs=typed"
        self.driver.get(url)
        self.driver.implicitly_wait(3)
        # Đợi ngắn để trang render kết quả (Pinterest load chậm sau login)
        time.sleep(2)

    def scroll_once(self) -> None:
        """Cuộn xuống cuối trang để Pinterest load thêm kết quả."""
        self.scroll_count += 1
        
        # Tự động rotate proxy sau mỗi N lần scroll
        if self.proxy_key and self.proxy_rotate_after > 0:
            if self.scroll_count >= self.proxy_rotate_after:
                print(f"[PROXY] Đã scroll {self.scroll_count} lần, đang rotate proxy...")
                self.rotate_proxy()
        
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(1.5, 2.5))

    def collect_image_urls(self, debug: bool = False) -> List[str]:
        """Parse HTML hiện tại để lấy URL chứa pinimg."""
        html = self.driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        urls: list[str] = []

        candidates: Iterable[str] = (
            img.get("src") or img.get("data-src") or "" for img in soup.find_all("img")
        )
        added = 0
        for url in candidates:
            if not url or url in self.seen:
                continue
            if not PIN_IMG_PATTERN.search(url):
                continue
            # Bỏ các thumbnail/video preview
            if "/videos/" in url:
                continue
            # Bỏ qua avatar/thumbnail rất nhỏ (60x60, 75x75_RS, v.v.)
            if "/60x60/" in url or "75x75_RS" in url:
                continue
            self.seen.add(url)
            urls.append(url)
            added += 1
        if debug:
            print(f"[DEBUG] Thu được {added} ảnh mới, tổng {len(self.seen)}")
        return urls

    def crawl(
        self,
        max_images: int,
        max_pages: int,
        debug: bool = False,
        patience: int = 7,  # số lần scroll liên tiếp không có ảnh mới thì dừng
    ) -> List[str]:
        """
        Cuộn tối đa max_pages lần hoặc cho đến khi gom đủ max_images URL.
        Nếu sau `patience` lần scroll liên tiếp không có ảnh mới -> dừng sớm.
        """
        collected: list[str] = []
        no_new_count = 0

        for page in range(max_pages):
            new_urls = self.collect_image_urls(debug=debug)

            if new_urls:
                collected.extend(new_urls)
                no_new_count = 0  # reset vì có ảnh mới
            else:
                no_new_count += 1
                if debug:
                    print(
                        f"[DEBUG] Scroll {page+1}: không có ảnh mới "
                        f"({no_new_count}/{patience})"
                    )

            # đủ ảnh thì dừng
            if len(collected) >= max_images:
                break

            # quá số lần cho phép mà không có ảnh mới -> end
            if no_new_count >= patience:
                print(
                    f"[MAIN] Không có ảnh mới sau {patience} lần scroll liên tiếp, dừng crawl."
                )
                break

            self.scroll_once()

        return collected[:max_images]

    def close(self) -> None:
        try:
            self.driver.quit()
        except WebDriverException:
            pass


def download_image(url: str, dest: Path) -> bool:
    """Tải một ảnh, trả về True nếu thành công."""
    try:
        # Pinterest thường có nhiều size; ưu tiên bản gốc nếu tìm thấy
        normalized = to_original_url(url)
        with requests.get(normalized, stream=True, timeout=20) as r:
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        return True
    except requests.RequestException:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawler Pinterest kiểu infinite scroll (Selenium)."
    )
    parser.add_argument("keyword", help="Từ khóa tìm kiếm, ví dụ: 'sunset beach'")
    parser.add_argument(
        "-n",
        "--num",
        type=int,
        default=20,
        help="Số ảnh tối đa cần tải (mặc định 20)",
    )
    parser.add_argument(
        "-p",
        "--pages",
        type=int,
        default=30,
        help="Số lần cuộn trang tối đa (mặc định 30)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="downloads",
        help="Thư mục lưu ảnh (mặc định: downloads)",
    )
    parser.add_argument(
        "--email",
        help="Email tài khoản Pinterest (để tự động đăng nhập)",
        default="",
    )
    parser.add_argument(
        "--password",
        help="Password tài khoản Pinterest (để tự động đăng nhập)",
        default="",
    )
    parser.add_argument(
        "--cookies",
        help="Đường dẫn file cookies.pkl (dùng/ghi lại session)",
        default="cookies.pkl",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Chạy Chrome headless",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ liệt kê URL, không tải ảnh",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="In log debug từng bước parse",
    )
    parser.add_argument(
        "--proxy-key",
        dest="proxy_key",
        help="Key proxy từ ckey.vn để tránh bị chặn IP. Nếu không cung cấp, sẽ tự động đọc từ file .proxy_key hoặc biến môi trường PROXY_KEY",
        default=None,
    )
    parser.add_argument(
        "--proxy-nhamang",
        dest="proxy_nhamang",
        help="Nhà mạng proxy: Random, Viettel, Vinaphone, fpt (mặc định: Random)",
        default="Random",
    )
    parser.add_argument(
        "--proxy-tinhthanh",
        dest="proxy_tinhthanh",
        help="Tỉnh thành proxy: 0=Random, 3=Hà Nội, 6=Hồ Chí Minh, ... (mặc định: 0)",
        default="0",
    )
    parser.add_argument(
        "--proxy-rotate-after",
        dest="proxy_rotate_after",
        type=int,
        help="Số lần scroll trước khi tự động rotate proxy (mặc định: 50, đặt 0 để tắt auto rotate)",
        default=50,
    )

    args = parser.parse_args()
    
    # Tự động load proxy key nếu không được cung cấp
    proxy_key = args.proxy_key
    if not proxy_key:
        print("[PROXY] Đang tìm proxy key từ file hoặc environment variable...")
        proxy_key = load_proxy_key()
        if proxy_key:
            print(f"[PROXY] Đã tự động load proxy key từ file hoặc environment variable")
        else:
            print("[PROXY] Không tìm thấy proxy key, sẽ chạy không proxy")
    
    # Nếu có proxy_key từ command line và chưa có trong file, lưu lại
    if args.proxy_key and not PROXY_KEY_FILE.exists():
        save_proxy_key(args.proxy_key)
        print(f"[PROXY] Đã lưu proxy key vào file .proxy_key (sẽ tự động dùng lần sau)")

    print(f"[MAIN] Đang khởi tạo crawler...")
    print(f"[MAIN] Proxy key: {'Có' if proxy_key else 'Không'}")
    print(f"[MAIN] Headless: {args.headless}")
    
    try:
        crawler = InfinitePinterestCrawler(
            headless=args.headless,
            cookies_path=args.cookies,
            proxy_key=proxy_key,
            proxy_nhamang=args.proxy_nhamang,
            proxy_tinhthanh=args.proxy_tinhthanh,
            proxy_rotate_after=args.proxy_rotate_after,
        )
        print(f"[MAIN] Đã khởi tạo crawler thành công")
    except Exception as e:
        print(f"[MAIN] Lỗi khi khởi tạo crawler: {e}")
        import traceback
        traceback.print_exc()
        return
    try:
        print(f"Đang mở tìm kiếm cho từ khóa: {args.keyword!r}")
        # Nếu đã login sẵn bằng cookies thì không cần thử email/password nữa
        if crawler.is_logged_in():
            if args.debug:
                print("Đã đăng nhập sẵn bằng cookies.")
        elif args.email and args.password:
            ok = crawler.login(args.email, args.password, debug=args.debug)
            if ok:
                print("Đăng nhập bằng email/password thành công.")
            else:
                print("Đăng nhập bằng email/password thất bại, tiếp tục crawl không đăng nhập.")
        elif args.debug:
            print("Không dùng email/password, crawl không đăng nhập.")
        crawler.open_search(args.keyword)

        urls = crawler.crawl(
            max_images=args.num, max_pages=args.pages, debug=args.debug
        )
        if not urls:
            print("Không tìm thấy URL ảnh nào. Có thể Pinterest yêu cầu đăng nhập.")
            return

        out_dir = Path(args.output)
        print(f"Thu được {len(urls)} URL. Lưu vào {out_dir.resolve()}")

        # Chuẩn hóa keyword để dùng trong tên file (chỉ chữ, số, gạch dưới)
        safe_keyword = re.sub(r"[^0-9A-Za-z]+", "_", args.keyword).strip("_") or "pinterest"
        
        # Lưu danh sách URL vào file text
        urls_file = out_dir / f"{safe_keyword}_urls.txt"
        out_dir.mkdir(parents=True, exist_ok=True)
        normalized_urls = [to_original_url(url) for url in urls]
        with open(urls_file, "w", encoding="utf-8") as f:
            for url in normalized_urls:
                f.write(url + "\n")
        print(f"Đã lưu {len(normalized_urls)} link ảnh vào: {urls_file.resolve()}")

        if args.dry_run:
            for i, url in enumerate(normalized_urls, 1):
                print(f"[{i:02d}] {url}")
            return

        for idx, url in enumerate(urls, 1):
            ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
            dest = out_dir / f"{safe_keyword}_{idx:03d}{ext}"
            ok = download_image(url, dest)
            status = "OK" if ok else "FAIL"
            print(f"[{idx:02d}] {status} -> {dest.name}")
            time.sleep(random.uniform(0.3, 0.8))  # nghỉ ngắn để giảm nguy cơ bị chặn
    finally:
        crawler.close()


if __name__ == "__main__":
    main()
