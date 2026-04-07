#!/usr/bin/env python3
"""
Shopee Crawler với Cookie Persistence - IMPROVED HEADLESS MODE
- Cập nhật: Lấy thêm Tên sản phẩm, Giá và Discount (theo cấu trúc HTML mới)
"""
import argparse
import json
import os
import random
import re
import time
from pathlib import Path
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup
try:
    import undetected_chromedriver as uc
except ImportError:
    print("⚠️  Cần cài: pip install undetected-chromedriver beautifulsoup4")
    exit(1)

try:
    import requests
except ImportError:
    print("⚠️  Cần cài: pip install requests")
    exit(1)

BASE = "https://shopee.vn"
COOKIE_FILE = Path.home() / ".shopee_cookies.json"

# API Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "https://stylid-dev.tipai.tech")
SHOPPING_ITEM_API = f"{API_BASE_URL}/api/v1/shopping-item/create"


def create_shopping_item(image: str, link: str, content: str, price: str, discount: int = None, debug: bool = False, timeout: int = 60, max_retries: int = 2):
    """
    Gọi API để tạo shopping item
    CHỜ response hoàn toàn trước khi trả về kết quả
    
    Args:
        image: URL ảnh sản phẩm
        link: URL sản phẩm
        content: Tên/mô tả sản phẩm
        price: Giá sản phẩm (dạng string số)
        discount: Phần trăm giảm giá (optional)
        debug: Bật debug mode
        timeout: Thời gian chờ timeout (giây), mặc định 60s
        max_retries: Số lần retry khi timeout, mặc định 2 lần
    
    Returns:
        dict: {"success": bool, "data": dict hoặc None, "error": str hoặc None}
    """
    payload = {
        "image": image,
        "link": link,
        "content": content,
        "price": str(price)
    }
    
    if discount is not None:
        payload["discount"] = int(discount)
    
    # Retry logic khi timeout
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if debug and attempt > 0:
                print(f"[API] Retry lần {attempt}/{max_retries} cho: {content[:50]}...")
            elif debug:
                print(f"[API] Đang gửi request (timeout={timeout}s): {content[:50]}...")
            
            # Gọi API và CHỜ response hoàn toàn (requests.post là blocking)
            response = requests.post(
                SHOPPING_ITEM_API, 
                json=payload, 
                timeout=timeout,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
            )
        
            # Đảm bảo đã nhận được response hoàn toàn
            # Kiểm tra status code trước khi parse
            if response.status_code in [200, 201]:
                # Parse response JSON khi thành công
                try:
                    data = response.json()
                except ValueError:
                    # Nếu không phải JSON, vẫn coi là thành công
                    data = {"status": "success", "message": response.text[:200]}
                
                if debug:
                    print(f"[API] ✓ Response thành công (HTTP {response.status_code}): {content[:50]}...")
                return {"success": True, "data": data, "error": None}
            else:
                # Status code không thành công - không retry
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                if debug:
                    print(f"[API] ✗ Response lỗi: {error_msg}")
                return {"success": False, "data": None, "error": error_msg}
                
        except requests.exceptions.HTTPError as e:
            # HTTP error (4xx, 5xx) - không retry
            error_msg = f"HTTP Error {e.response.status_code}: {e.response.text[:200] if e.response else str(e)}"
            if debug:
                print(f"[API] ✗ HTTP Error: {error_msg}")
            return {"success": False, "data": None, "error": error_msg}
        except requests.exceptions.Timeout:
            # Timeout - có thể retry
            last_error = f"Request timeout sau {timeout} giây"
            if attempt < max_retries:
                wait_time = (attempt + 1) * 2  # Exponential backoff: 2s, 4s, 6s...
                if debug:
                    print(f"[API] ⏱️  Timeout, đợi {wait_time}s trước khi retry...")
                time.sleep(wait_time)
                continue  # Retry
            else:
                # Hết số lần retry
                if debug:
                    print(f"[API] ✗ Timeout sau {max_retries + 1} lần thử: {last_error}")
                return {"success": False, "data": None, "error": last_error}
        except requests.exceptions.RequestException as e:
            # Connection error - có thể retry
            last_error = f"Lỗi kết nối: {str(e)}"
            if attempt < max_retries:
                wait_time = (attempt + 1) * 2
                if debug:
                    print(f"[API] ⚠️  Lỗi kết nối, đợi {wait_time}s trước khi retry...")
                time.sleep(wait_time)
                continue  # Retry
            else:
                if debug:
                    print(f"[API] ✗ Connection Error sau {max_retries + 1} lần thử: {last_error}")
                return {"success": False, "data": None, "error": last_error}
        except Exception as e:
            # Unknown error - không retry
            error_msg = f"Lỗi không xác định: {str(e)}"
            if debug:
                print(f"[API] ✗ Unknown Error: {error_msg}")
            return {"success": False, "data": None, "error": error_msg}
    
    # Nếu đến đây nghĩa là đã hết retry
    return {"success": False, "data": None, "error": last_error or "Lỗi không xác định"}


def send_products_to_api(products: list, debug: bool = False, timeout: int = 60, max_retries: int = 2):
    """
    Gửi danh sách sản phẩm lên API
    
    Args:
        products: List các tuple (name, img_url, product_url, price, discount_percent)
        debug: Bật debug mode
        timeout: Thời gian chờ timeout cho mỗi request (giây), mặc định 60s
        max_retries: Số lần retry khi timeout, mặc định 2 lần
    
    Returns:
        dict: {"total": int, "success": int, "failed": int, "errors": list}
    """
    if not products:
        return {"total": 0, "success": 0, "failed": 0, "errors": []}
    
    print(f"\n{'='*60}")
    print(f"📤 Đang gửi {len(products)} sản phẩm lên API...")
    print(f"{'='*60}\n")
    
    results = {"total": len(products), "success": 0, "failed": 0, "errors": []}
    
    for idx, item_data in enumerate(products, 1):
        name, img_url, product_url, price, discount_percent = item_data
        
        # Chuyển đổi giá thành string
        price_str = str(int(price)) if price else "0"
        
        # Gọi API và CHỜ response thành công trước khi tiếp tục
        print(f"[{idx}/{len(products)}] Đang gửi: {name[:60]}...")
        result = create_shopping_item(
            image=img_url,
            link=product_url,
            content=name,
            price=price_str,
            discount=discount_percent if discount_percent else None,
            debug=debug,
            timeout=timeout,
            max_retries=max_retries
        )
        
        # Chỉ tiếp tục khi đã có response (thành công hoặc thất bại)
        if result["success"]:
            results["success"] += 1
            print(f"[{idx}/{len(products)}] ✓ Thành công: {name[:60]}...")
            # Chỉ delay sau khi thành công để tránh rate limit
            time.sleep(0.5)
        else:
            results["failed"] += 1
            error_info = {
                "index": idx,
                "name": name,
                "error": result["error"]
            }
            results["errors"].append(error_info)
            print(f"[{idx}/{len(products)}] ✗ Thất bại: {name[:60]}... - {result['error']}")
            # Vẫn delay một chút khi thất bại để tránh spam
            time.sleep(0.3)
    
    print(f"\n{'='*60}")
    print(f"📊 KẾT QUẢ GỬI API:")
    print(f"  ✓ Thành công: {results['success']}/{results['total']}")
    print(f"  ✗ Thất bại: {results['failed']}/{results['total']}")
    print(f"{'='*60}\n")
    
    return results


def build_driver(headless: bool = False):
    """Tạo undetected Chrome driver với improved stealth"""
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=vi-VN")
    
    # User agent giống thật
    options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-web-security")
        options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    
    driver = uc.Chrome(options=options, version_main=146)
    
    if headless:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US', 'en'] });
                window.chrome = { runtime: {} };
            """
        })
    
    return driver


def save_cookies(driver, filepath: Path):
    try:
        cookies = driver.get_cookies()
        with open(filepath, 'w') as f:
            json.dump(cookies, f, indent=2)
        print(f"✅ Đã lưu cookies vào {filepath}")
        return True
    except Exception as e:
        print(f"❌ Không thể lưu cookies: {e}")
        return False


def is_driver_alive(driver):
    try:
        driver.current_window_handle
        return True
    except Exception:
        return False


def load_cookies(driver, filepath: Path, debug: bool = False):
    if not filepath.exists():
        if debug:
            print(f"[DEBUG] Cookie file không tồn tại: {filepath}")
        return False
    
    try:
        if not is_driver_alive(driver):
            if debug:
                print("[DEBUG] Driver không còn hoạt động khi load cookies")
            return False
        
        with open(filepath, 'r') as f:
            cookies = json.load(f)
        
        if not cookies:
            if debug:
                print("[DEBUG] Cookie file rỗng")
            return False
        
        try:
            driver.get(BASE)
            time.sleep(3)
        except Exception as e:
            if debug:
                print(f"[DEBUG] Không thể truy cập {BASE}: {e}")
            return False
        
        if not is_driver_alive(driver):
            if debug:
                print("[DEBUG] Driver đã đóng sau khi navigate")
            return False
        
        loaded_count = 0
        for cookie in cookies:
            if 'expiry' in cookie:
                cookie['expiry'] = int(cookie['expiry'])
            try:
                driver.add_cookie(cookie)
                loaded_count += 1
            except Exception as e:
                if debug:
                    print(f"[DEBUG] Không thể add cookie: {e}")
                pass
        
        if loaded_count > 0:
            print(f"✅ Đã load {loaded_count}/{len(cookies)} cookies thành công")
            return True
        else:
            if debug:
                print("[DEBUG] Không load được cookie nào")
            return False
            
    except json.JSONDecodeError as e:
        print(f"⚠️  Cookie file bị lỗi định dạng: {e}")
        return False
    except Exception as e:
        if debug:
            print(f"[DEBUG] Lỗi khi load cookies: {e}")
        return False


def manual_login(driver, debug: bool = False):
    print("\n" + "="*60)
    print("🔐 ĐĂNG NHẬP SHOPEE")
    print("="*60)
    print("1. Một cửa sổ trình duyệt sẽ mở")
    print("2. Vui lòng đăng nhập vào Shopee")
    print("3. Sau khi đăng nhập xong, quay lại đây nhấn Enter")
    print("="*60)
    
    try:
        if not is_driver_alive(driver):
            print("❌ Trình duyệt đã đóng, không thể đăng nhập")
            return False
        
        driver.get(f"{BASE}/buyer/login")
        time.sleep(2)
        
        if not is_driver_alive(driver):
            print("❌ Trình duyệt đã đóng sau khi mở trang login")
            return False
        
    except Exception as e:
        print(f"❌ Lỗi khi mở trang login: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        return False
    
    try:
        input("\n⏸️  Nhấn Enter sau khi đã đăng nhập xong... ")
    except (EOFError, KeyboardInterrupt):
        print("\n⚠️  Đã hủy đăng nhập")
        return False
    
    try:
        if not is_driver_alive(driver):
            print("❌ Trình duyệt đã đóng")
            return False
        
        driver.get(BASE)
        time.sleep(2)
        
        if not is_driver_alive(driver):
            print("❌ Trình duyệt đã đóng khi kiểm tra đăng nhập")
            return False
        
        current_url = driver.current_url
        if "login" not in current_url:
            print("✅ Đăng nhập thành công!")
            save_cookies(driver, COOKIE_FILE)
            return True
        else:
            print(f"❌ Chưa đăng nhập thành công. URL hiện tại: {current_url}")
            return False
    except Exception as e:
        print(f"❌ Lỗi khi kiểm tra đăng nhập: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        return False


def ensure_logged_in(driver, force_login: bool = False, headless: bool = False, debug: bool = False):
    if headless and not COOKIE_FILE.exists():
        print("\n❌ LỖI: Chế độ headless yêu cầu cookie đã lưu!")
        return False
    
    if headless and force_login:
        print("\n❌ LỖI: Không thể dùng --relogin với --headless!")
        return False
    
    if force_login:
        print("🔄 Bắt buộc đăng nhập lại...")
        if COOKIE_FILE.exists():
            COOKIE_FILE.unlink()
            print("🗑️  Đã xóa cookie cũ")
        return manual_login(driver, debug=debug)
    
    if COOKIE_FILE.exists():
        print("🍪 Tìm thấy cookies đã lưu, đang load...")
        if load_cookies(driver, COOKIE_FILE, debug=debug):
            if not is_driver_alive(driver):
                print("⚠️  Trình duyệt đã đóng sau khi load cookies")
                return False
            
            try:
                driver.get(BASE)
                time.sleep(3)
                
                if not is_driver_alive(driver):
                    print("⚠️  Trình duyệt đã đóng khi kiểm tra cookie")
                    return False
                
                current_url = driver.current_url
                if "login" not in current_url:
                    print("✅ Cookie vẫn còn hiệu lực!")
                    return True
                else:
                    print("⚠️  Cookie đã hết hạn, cần đăng nhập lại")
                    COOKIE_FILE.unlink()
                    # Chỉ gọi manual_login nếu không phải headless
                    if not headless:
                        print("🔄 Đang yêu cầu đăng nhập lại...")
                        return manual_login(driver, debug=debug)
                    return False
            except Exception as e:
                print(f"⚠️  Lỗi khi kiểm tra cookie: {e}")
                if debug:
                    import traceback
                    traceback.print_exc()
                return False
        else:
            print("⚠️  Không thể load cookies")
            if headless:
                return False
            # Nếu không phải headless, thử đăng nhập thủ công
            print("🔄 Thử đăng nhập thủ công...")
            return manual_login(driver, debug=debug)
    
    # Không có cookie file
    if headless:
        print("\n❌ Cookie không có hoặc đã hết hạn trong headless mode")
        return False
    
    # Không phải headless, cho phép đăng nhập thủ công
    print("📝 Không có cookie, cần đăng nhập lần đầu...")
    return manual_login(driver, debug=debug)


def human_like_scroll(driver):
    try:
        total_height = driver.execute_script("return document.body.scrollHeight")
        current_position = 0
        while current_position < total_height:
            scroll_amount = random.randint(200, 400)
            current_position += scroll_amount
            driver.execute_script(f"window.scrollTo(0, {current_position});")
            time.sleep(random.uniform(0.2, 0.5))
            total_height = driver.execute_script("return document.body.scrollHeight")
    except Exception:
        pass


def scroll_infinite(driver, max_pages: int = 10):
    try:
        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(max_pages):
            human_like_scroll(driver)
            time.sleep(random.uniform(1.5, 2.5))
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
    except Exception:
        pass


def parse_price(price_text):
    if not price_text:
        return None
    price_clean = re.sub(r'[^\d.,]', '', price_text)
    price_clean = price_clean.replace(',', '').replace('.', '')
    if price_clean:
        try:
            return float(price_clean)
        except ValueError:
            return None
    return None


def extract_product_name(item_element):
    """
    Trích xuất tên sản phẩm từ:
    1. Thuộc tính alt của ảnh (thường chứa tên đầy đủ)
    2. Thẻ div có class line-clamp-2 (tên hiển thị)
    """
    # Cách 1: Lấy từ alt của ảnh (Ưu tiên vì thường đầy đủ hơn)
    img = item_element.find("img")
    if img:
        alt_text = img.get("alt")
        if alt_text and len(alt_text) > 5:
            return alt_text.strip()

    # Cách 2: Lấy từ text hiển thị (class line-clamp-2)
    name_selectors = [
        "div.line-clamp-2", 
        "div[class*='line-clamp-2']",
        "div.break-words"
    ]
    
    for selector in name_selectors:
        name_elem = item_element.select_one(selector)
        if name_elem:
            text = name_elem.get_text(strip=True)
            if len(text) > 5:
                return text

    return "Không tên"


def extract_price_info(item_element, debug=False):
    """Trích xuất giá và phần trăm giảm giá từ element sản phẩm"""
    price = None
    original_price = None
    discount_percent = None
    
    try:
        # 1. Tìm giá hiện tại
        price_selectors = [
            r"div.items-baseline span.text-base\/5",  # Selector mới
            "div.items-baseline span",
            "span.text-shopee-primary",
            "span[class*='price']"
        ]
        
        for selector in price_selectors:
            price_elems = item_element.select(selector)
            for price_elem in price_elems:
                price_text = price_elem.get_text(strip=True)
                if price_text == 'đ' or len(price_text) < 3:
                    continue
                parsed_price = parse_price(price_text)
                if parsed_price and parsed_price > 0:
                    if price is None or parsed_price < price:
                        price = parsed_price
            if price: break
        
        # 2. Tìm Discount (%)
        discount_selectors = [
            "div.bg-shopee-pink",  # Selector mới
            "span.bg-shopee-pink",
            "div[class*='discount']",
            "span[class*='percent']"
        ]
        
        for selector in discount_selectors:
            discount_elems = item_element.select(selector)
            for discount_elem in discount_elems:
                discount_text = discount_elem.get_text(strip=True)
                percent_match = re.search(r'(\d+)%', discount_text)
                if percent_match:
                    discount_percent = int(percent_match.group(1))
                    break
            if discount_percent: break
            
    except Exception as e:
        if debug: print(f"[DEBUG] Extract price error: {e}")
            
    return price, original_price, discount_percent


def fetch_products(driver, keyword: str, max_items: int = 30, debug: bool = False):
    """Crawl sản phẩm từ Shopee"""
    search_url = f"{BASE}/search?keyword={quote_plus(keyword)}"
    print(f"\n🔍 Đang tìm kiếm: {keyword}")
    
    try:
        driver.get(search_url)
        time.sleep(random.uniform(3, 5))
    except Exception:
        return []
    
    if "login" in driver.current_url:
        print("⚠️  Bị redirect sang trang login!")
        return []
    
    print("📜 Đang cuộn trang để load sản phẩm...")
    scroll_infinite(driver, max_pages=max(3, max_items // 20))
    time.sleep(2)
    
    html = driver.page_source
    if debug:
        with open("/tmp/shopee_debug.html", 'w', encoding='utf-8') as f:
            f.write(html)
            
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()
    
    item_selectors = ["div[data-sqe='item']", "a[href*='-i.']"]
    
    for item_selector in item_selectors:
        if len(results) >= max_items: break
        items = soup.select(item_selector)
        
        for item in items:
            if len(results) >= max_items: break
            
            a = item if item.name == 'a' else item.find("a", href=lambda x: x and "-i." in x)
            if not a: continue
            
            href = a.get("href", "")
            if not href or "-i." not in href: continue
            product_url = urljoin(BASE, href) if href.startswith("/") else href
            
            img = item.find("img")
            if not img: continue
            img_url = img.get("src") or img.get("data-src") or ""
            if not img_url or img_url.startswith("data:"): continue
            if img_url.startswith("//"): img_url = "https:" + img_url
            
            # --- TRÍCH XUẤT DỮ LIỆU ---
            name = extract_product_name(item) # Lấy tên sản phẩm
            price, original_price, discount_percent = extract_price_info(item, debug=debug)
            
            key = (img_url, product_url)
            if key not in seen:
                seen.add(key)
                # Tuple kết quả bây giờ có 5 phần tử
                results.append((name, img_url, product_url, price, discount_percent))
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Shopee Crawler")
    parser.add_argument("keyword", help="Từ khóa")
    parser.add_argument("-n", "--num", type=int, default=30, help="Số lượng")
    parser.add_argument("--headless", action="store_true", help="Chạy ẩn")
    parser.add_argument("--debug", action="store_true", help="Debug")
    parser.add_argument("--relogin", action="store_true", help="Login lại")
    parser.add_argument("--api", action="store_true", help="Gửi sản phẩm lên API sau khi crawl")
    parser.add_argument("--api-url", type=str, default=None, help="URL API (mặc định: từ env API_BASE_URL)")
    parser.add_argument("--api-timeout", type=int, default=60, help="Timeout cho mỗi API request (giây), mặc định 60s")
    parser.add_argument("--api-retries", type=int, default=2, help="Số lần retry khi timeout, mặc định 2 lần")
    args = parser.parse_args()
    
    # Cập nhật API URL nếu được chỉ định
    global SHOPPING_ITEM_API
    if args.api_url:
        SHOPPING_ITEM_API = f"{args.api_url}/api/v1/shopping-item/create"
    
    print("🚀 Shopee Crawler - Full Info Version")
    
    driver = None
    try:
        # Tạo driver
        driver = build_driver(headless=args.headless)
        
        # Đảm bảo đã đăng nhập
        login_success = ensure_logged_in(driver, force_login=args.relogin, headless=args.headless, debug=args.debug)
        
        if not login_success:
            print("\n❌ Không thể đăng nhập. Thoát chương trình.")
            print("💡 Gợi ý:")
            if args.headless:
                print("   - Chạy KHÔNG có --headless để đăng nhập lần đầu:")
                print("     python3 shopeeCrawler.py \"áo dài\" -n 20")
                print("   - Sau khi đăng nhập, cookie sẽ được lưu tự động")
            else:
                print("   - Kiểm tra lại thông tin đăng nhập")
                print("   - Hoặc thử chạy với --relogin để đăng nhập lại:")
                print("     python3 shopeeCrawler.py \"áo dài\" -n 20 --relogin")
            return
        
        # Kiểm tra lại một lần nữa để chắc chắn đã đăng nhập
        try:
            driver.get(BASE)
            time.sleep(2)
            if "login" in driver.current_url:
                print("\n⚠️  Cảnh báo: Có vẻ như chưa đăng nhập thành công!")
                print("💡 Thử chạy lại với --relogin")
                return
        except Exception as e:
            print(f"\n⚠️  Lỗi khi kiểm tra đăng nhập: {e}")
            return

        pairs = fetch_products(driver, args.keyword, max_items=args.num, debug=args.debug)
        
        if not pairs:
            print("\n❌ Không lấy được sản phẩm nào!")
            return
        
        print(f"\n✅ Thành công! Lấy được {len(pairs)} sản phẩm\n")
        print("="*100)
        
        for i, item_data in enumerate(pairs, 1):
            # Unpack 5 giá trị
            name, img, prod, price, discount_percent = item_data
            
            print(f"\n[{i:02d}] {name}") # In tên sản phẩm lên đầu
            print(f"  🖼️  Ảnh: {img}")
            print(f"  🔗 Link: {prod}")
            
            if price:
                print(f"  💰 Giá: {price:,.0f} đ".replace(",", "."))
            else:
                print(f"  💰 Giá: ???")
            
            if discount_percent:
                print(f"  🏷️  Giảm: {discount_percent}%")
            
        print("\n" + "="*100)
        
        # Gửi lên API nếu được yêu cầu
        if args.api:
            send_products_to_api(
                pairs, 
                debug=args.debug,
                timeout=args.api_timeout,
                max_retries=args.api_retries
            )
        
    except KeyboardInterrupt:
        print("\n🛑 Đã dừng")
    except Exception as e:
        print(f"\n❌ Lỗi: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
    finally:
        if driver:
            try: driver.quit()
            except: pass

if __name__ == "__main__":
    main()