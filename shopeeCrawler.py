#!/usr/bin/env python3
"""
Shopee Crawler - Multi keyword, xuất 1 file tổng hợp CSV / JSON
Dùng:
  python3 shopeeCrawler.py -k "áo dài" "quần vintage" "giày cao gót" -n 20
  python3 shopeeCrawler.py -f keywords.txt -n 30 --format both
  python3 shopeeCrawler.py -k "áo dài" -n 10 --format json --output ket_qua
"""
import argparse
import csv
import json
import os
import random
import re
import subprocess
import time
from datetime import datetime
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

BASE             = "https://shopee.vn"
COOKIE_FILE      = Path.home() / ".shopee_cookies.json"
API_BASE_URL     = os.getenv("API_BASE_URL", "https://stylid-dev.tipai.tech")
SHOPPING_ITEM_API = f"{API_BASE_URL}/api/v1/shopping-item/create"


# ─────────────────────────────────────────────
# CHROME
# ─────────────────────────────────────────────

def get_chrome_version() -> int:
    paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
    ]
    for path in paths:
        try:
            out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5).stdout
            m = re.search(r"(\d+)\.", out)
            if m:
                v = int(m.group(1))
                print(f"🔍 Chrome version: {v}")
                return v
        except Exception:
            continue
    print("⚠️  Không detect được Chrome version, dùng 146")
    return 146


def build_driver(headless: bool = False, chrome_version: int = None) -> uc.Chrome:
    if chrome_version is None:
        chrome_version = get_chrome_version()

    options = uc.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=vi-VN")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--no-service-autorun")
    options.add_argument("--password-store=basic")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-translate")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-sync")
    options.add_argument("--metrics-recording-only")
    options.add_argument("--disable-default-apps")
    options.add_argument("--mute-audio")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{chrome_version}.0.0.0 Safari/537.36"
    )
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")

    print(f"🚗 Khởi động Chrome {chrome_version}...")
    driver = uc.Chrome(options=options, version_main=chrome_version, use_subprocess=True)
    time.sleep(3)

    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": """
            Object.defineProperty(navigator, 'webdriver',  { get: () => undefined });
            Object.defineProperty(navigator, 'plugins',    { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages',  { get: () => ['vi-VN','vi','en-US','en'] });
            window.chrome = { runtime: {} };
        """})
    except Exception:
        pass

    return driver


def is_driver_alive(driver) -> bool:
    try:
        _ = driver.current_window_handle
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────
# COOKIE / LOGIN
# ─────────────────────────────────────────────

def save_cookies(driver, filepath: Path) -> bool:
    try:
        cookies = driver.get_cookies()
        with open(filepath, "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"✅ Đã lưu {len(cookies)} cookies → {filepath}")
        return True
    except Exception as e:
        print(f"❌ Lưu cookies thất bại: {e}")
        return False


def load_cookies(driver, filepath: Path, debug: bool = False) -> bool:
    if not filepath.exists():
        return False
    try:
        with open(filepath) as f:
            cookies = json.load(f)
        if not cookies:
            return False

        driver.get(BASE)
        time.sleep(3)
        if not is_driver_alive(driver):
            return False

        loaded = 0
        for c in cookies:
            if "expiry" in c:
                c["expiry"] = int(c["expiry"])
            try:
                driver.add_cookie(c)
                loaded += 1
            except Exception as e:
                if debug:
                    print(f"[DEBUG] Bỏ qua cookie: {e}")

        if loaded > 0:
            print(f"✅ Load {loaded}/{len(cookies)} cookies")
            return True
        return False
    except Exception as e:
        if debug:
            print(f"[DEBUG] load_cookies: {e}")
        return False


def manual_login(driver, debug: bool = False) -> bool:
    print("\n" + "=" * 60)
    print("🔐 ĐĂNG NHẬP SHOPEE")
    print("=" * 60)
    print("1. Cửa sổ trình duyệt sẽ mở trang đăng nhập")
    print("2. Vui lòng đăng nhập vào Shopee")
    print("3. Sau khi đăng nhập xong, quay lại đây nhấn Enter")
    print("=" * 60)

    try:
        if not is_driver_alive(driver):
            print("❌ Trình duyệt đã đóng")
            return False
        driver.get(f"{BASE}/buyer/login")
        time.sleep(3)
        if not is_driver_alive(driver):
            print("❌ Trình duyệt đóng sau khi mở login")
            return False
    except Exception as e:
        print(f"❌ Lỗi mở trang login: {e}")
        if debug:
            import traceback; traceback.print_exc()
        return False

    try:
        input("\n⏸️  Nhấn Enter sau khi đã đăng nhập xong... ")
    except (EOFError, KeyboardInterrupt):
        print("\n⚠️  Đã hủy")
        return False

    try:
        if not is_driver_alive(driver):
            print("❌ Trình duyệt đã đóng")
            return False
        driver.get(BASE)
        time.sleep(3)
        if "login" not in driver.current_url:
            print("✅ Đăng nhập thành công!")
            save_cookies(driver, COOKIE_FILE)
            return True
        print(f"❌ Chưa đăng nhập. URL: {driver.current_url}")
        return False
    except Exception as e:
        print(f"❌ Lỗi kiểm tra đăng nhập: {e}")
        if debug:
            import traceback; traceback.print_exc()
        return False


def ensure_logged_in(driver, force_login=False, headless=False, debug=False) -> bool:
    if headless and not COOKIE_FILE.exists():
        print("❌ Headless mode cần cookie có sẵn!")
        return False
    if headless and force_login:
        print("❌ Không thể dùng --relogin với --headless!")
        return False

    if force_login:
        if COOKIE_FILE.exists():
            COOKIE_FILE.unlink()
            print("🗑️  Đã xóa cookie cũ")
        return manual_login(driver, debug=debug)

    if COOKIE_FILE.exists():
        print("🍪 Load cookies...")
        if load_cookies(driver, COOKIE_FILE, debug=debug):
            driver.get(BASE)
            time.sleep(3)
            if is_driver_alive(driver) and "login" not in driver.current_url:
                print("✅ Cookie còn hiệu lực!")
                return True
            print("⚠️  Cookie hết hạn")
            COOKIE_FILE.unlink()
            if headless:
                return False
            return manual_login(driver, debug=debug)
        if headless:
            return False
        return manual_login(driver, debug=debug)

    if headless:
        print("❌ Không có cookie trong headless mode")
        return False
    return manual_login(driver, debug=debug)


# ─────────────────────────────────────────────
# SCROLL
# ─────────────────────────────────────────────

def human_like_scroll(driver):
    try:
        total = driver.execute_script("return document.body.scrollHeight")
        pos = 0
        while pos < total:
            pos += random.randint(200, 400)
            driver.execute_script(f"window.scrollTo(0, {pos});")
            time.sleep(random.uniform(0.2, 0.5))
            total = driver.execute_script("return document.body.scrollHeight")
    except Exception:
        pass


def scroll_infinite(driver, max_rounds=10):
    try:
        last = driver.execute_script("return document.body.scrollHeight")
        for _ in range(max_rounds):
            human_like_scroll(driver)
            time.sleep(random.uniform(1.5, 2.5))
            new = driver.execute_script("return document.body.scrollHeight")
            if new == last:
                break
            last = new
    except Exception:
        pass


# ─────────────────────────────────────────────
# PARSE
# ─────────────────────────────────────────────

def parse_price(text: str):
    if not text:
        return None
    clean = re.sub(r"[^\d]", "", text)
    try:
        return float(clean) if clean else None
    except ValueError:
        return None


def extract_product_name(item) -> str:
    img = item.find("img")
    if img:
        alt = img.get("alt", "").strip()
        if len(alt) > 5:
            return alt
    for sel in ["div.line-clamp-2", "div[class*='line-clamp-2']", "div.break-words"]:
        el = item.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            if len(text) > 5:
                return text
    return "Không tên"


def extract_price_info(item, debug=False):
    price, discount_percent = None, None
    try:
        for sel in [r"div.items-baseline span.text-base\/5", "div.items-baseline span",
                    "span.text-shopee-primary", "span[class*='price']"]:
            for el in item.select(sel):
                text = el.get_text(strip=True)
                if text == "đ" or len(text) < 3:
                    continue
                p = parse_price(text)
                if p and p > 0 and (price is None or p < price):
                    price = p
            if price:
                break

        for sel in ["div.bg-shopee-pink", "span.bg-shopee-pink",
                    "div[class*='discount']", "span[class*='percent']"]:
            for el in item.select(sel):
                m = re.search(r"(\d+)%", el.get_text(strip=True))
                if m:
                    discount_percent = int(m.group(1))
                    break
            if discount_percent:
                break
    except Exception as e:
        if debug:
            print(f"[DEBUG] extract_price_info: {e}")
    return price, discount_percent


# ─────────────────────────────────────────────
# CRAWL
# ─────────────────────────────────────────────

def fetch_products(driver, keyword: str, max_items: int = 30, debug: bool = False) -> list:
    """Trả về list of dict, mỗi dict có thêm trường 'keyword'"""
    search_url = f"{BASE}/search?keyword={quote_plus(keyword)}"
    print(f"\n  🔍 Đang crawl: '{keyword}'")

    try:
        driver.get(search_url)
        time.sleep(random.uniform(3, 5))
    except Exception as e:
        print(f"  ❌ Không mở được trang: {e}")
        return []

    if "login" in driver.current_url:
        print("  ⚠️  Bị redirect login!")
        return []

    print("  📜 Đang cuộn trang...")
    scroll_infinite(driver, max_rounds=max(3, max_items // 20))
    time.sleep(2)

    html = driver.page_source
    if debug:
        path = f"/tmp/shopee_{re.sub(r'[^\\w]', '_', keyword)[:20]}.html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  [DEBUG] HTML → {path}")

    soup = BeautifulSoup(html, "html.parser")
    results, seen = [], set()

    for item_selector in ["div[data-sqe='item']", "a[href*='-i.']"]:
        if len(results) >= max_items:
            break
        for item in soup.select(item_selector):
            if len(results) >= max_items:
                break

            a = item if item.name == "a" else item.find("a", href=lambda x: x and "-i." in x)
            if not a:
                continue
            href = a.get("href", "")
            if not href or "-i." not in href:
                continue
            product_url = urljoin(BASE, href) if href.startswith("/") else href

            img = item.find("img")
            if not img:
                continue
            img_url = img.get("src") or img.get("data-src") or ""
            if not img_url or img_url.startswith("data:"):
                continue
            if img_url.startswith("//"):
                img_url = "https:" + img_url

            name = extract_product_name(item)
            price, discount = extract_price_info(item, debug=debug)

            key = (img_url, product_url)
            if key not in seen:
                seen.add(key)
                results.append({
                    "keyword":  keyword,
                    "ten":      name,
                    "gia":      int(price) if price else None,
                    "giam_gia": discount,
                    "anh":      img_url,
                    "link":     product_url,
                })

    print(f"  ✅ Lấy được {len(results)} sản phẩm cho '{keyword}'")
    return results


# ─────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────

def export_csv(all_products: list, filepath: Path):
    fields = ["stt", "keyword", "ten", "gia", "giam_gia", "anh", "link"]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for i, row in enumerate(all_products, 1):
            writer.writerow({
                "stt":      i,
                "keyword":  row["keyword"],
                "ten":      row["ten"],
                "gia":      row["gia"] if row["gia"] else "",
                "giam_gia": f"{row['giam_gia']}%" if row["giam_gia"] else "",
                "anh":      row["anh"],
                "link":     row["link"],
            })
    print(f"\n💾 CSV  ({len(all_products)} dòng) → {filepath}")


def export_json(all_products: list, filepath: Path):
    output = [{"stt": i, **row} for i, row in enumerate(all_products, 1)]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"💾 JSON ({len(all_products)} sản phẩm) → {filepath}")


# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────

def create_shopping_item(image, link, content, price, discount=None,
                         debug=False, timeout=60, max_retries=2) -> dict:
    payload = {"image": image, "link": link, "content": content, "price": str(price)}
    if discount is not None:
        payload["discount"] = int(discount)

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if debug:
                label = f"retry {attempt}" if attempt > 0 else f"timeout={timeout}s"
                print(f"  [API] Gửi ({label}): {content[:50]}...")
            resp = requests.post(
                SHOPPING_ITEM_API, json=payload, timeout=timeout,
                headers={"Content-Type": "application/json", "Accept": "application/json"}
            )
            if resp.status_code in [200, 201]:
                try:
                    data = resp.json()
                except ValueError:
                    data = {"status": "success"}
                return {"success": True, "data": data, "error": None}
            else:
                err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                return {"success": False, "data": None, "error": err}
        except requests.exceptions.Timeout:
            last_error = f"Timeout sau {timeout}s"
            if attempt < max_retries:
                time.sleep((attempt + 1) * 2)
        except requests.exceptions.RequestException as e:
            last_error = f"Lỗi kết nối: {e}"
            if attempt < max_retries:
                time.sleep((attempt + 1) * 2)
        except Exception as e:
            return {"success": False, "data": None, "error": str(e)}

    return {"success": False, "data": None, "error": last_error}


def send_products_to_api(all_products: list, debug=False, timeout=60, max_retries=2):
    total = len(all_products)
    print(f"\n{'='*60}\n📤 Gửi {total} sản phẩm lên API...\n{'='*60}\n")
    success = failed = 0

    for idx, row in enumerate(all_products, 1):
        name     = row["ten"]
        price    = str(row["gia"]) if row["gia"] else "0"
        discount = row["giam_gia"]
        print(f"[{idx}/{total}] {name[:60]}...")

        result = create_shopping_item(
            image=row["anh"], link=row["link"], content=name,
            price=price, discount=discount,
            debug=debug, timeout=timeout, max_retries=max_retries
        )
        if result["success"]:
            success += 1
            print(f"[{idx}/{total}] ✓ OK")
            time.sleep(0.5)
        else:
            failed += 1
            print(f"[{idx}/{total}] ✗ {result['error']}")
            time.sleep(0.3)

    print(f"\n{'='*60}")
    print(f"📊 KẾT QUẢ API: ✓ {success}/{total}  ✗ {failed}/{total}")
    print(f"{'='*60}\n")


# ─────────────────────────────────────────────
# KEYWORDS INPUT
# ─────────────────────────────────────────────

def load_keywords_from_file(filepath: str) -> list:
    """Đọc keywords từ file text, mỗi dòng 1 keyword, bỏ dòng trống và comment (#)"""
    path = Path(filepath)
    if not path.exists():
        print(f"❌ File không tồn tại: {filepath}")
        exit(1)
    keywords = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            kw = line.strip()
            if kw and not kw.startswith("#"):
                keywords.append(kw)
    if not keywords:
        print(f"❌ File '{filepath}' không có keyword nào!")
        exit(1)
    return keywords


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Shopee Crawler - Multi keyword → 1 file tổng hợp",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Ví dụ:
  # Crawl nhiều keyword trực tiếp
  python3 shopeeCrawler.py -k "áo dài" "quần vintage" "giày cao gót" -n 20

  # Đọc keyword từ file (mỗi dòng 1 keyword)
  python3 shopeeCrawler.py -f keywords.txt -n 30

  # Xuất cả CSV lẫn JSON, đặt tên file
  python3 shopeeCrawler.py -k "áo dài" --format both --output ket_qua_thang_4

  # Chạy ẩn + gửi API
  python3 shopeeCrawler.py -f keywords.txt --headless --api
        """
    )

    # Nguồn keyword (bắt buộc 1 trong 2)
    kw_group = parser.add_mutually_exclusive_group(required=True)
    kw_group.add_argument("-k", "--keywords", nargs="+", metavar="KW",
                          help="Một hoặc nhiều từ khóa, cách nhau bằng dấu cách")
    kw_group.add_argument("-f", "--file",     metavar="FILE",
                          help="File text chứa danh sách keyword (mỗi dòng 1 keyword)")

    parser.add_argument("-n", "--num",          type=int,   default=30,
                        help="Số sản phẩm mỗi keyword (mặc định 30)")
    parser.add_argument("--format",             choices=["csv", "json", "both"], default="csv",
                        help="Định dạng xuất file (mặc định: csv)")
    parser.add_argument("--output",             type=str,   default=None,
                        help="Tên file output không cần đuôi (mặc định: tự động theo ngày giờ)")
    parser.add_argument("--headless",           action="store_true",
                        help="Chạy ẩn - cần cookie có sẵn")
    parser.add_argument("--relogin",            action="store_true",
                        help="Xóa cookie cũ và đăng nhập lại")
    parser.add_argument("--debug",              action="store_true",
                        help="Bật debug")
    parser.add_argument("--chrome-version",     type=int,   default=None,
                        help="Chỉ định Chrome version thủ công (vd: 146)")
    parser.add_argument("--delay",              type=float, default=3.0,
                        help="Thời gian nghỉ giữa các keyword (giây, mặc định 3)")
    parser.add_argument("--api",                action="store_true",
                        help="Gửi toàn bộ sản phẩm lên API sau khi crawl xong")
    parser.add_argument("--api-url",            type=str,   default=None,
                        help="URL API tuỳ chỉnh")
    parser.add_argument("--api-timeout",        type=int,   default=60)
    parser.add_argument("--api-retries",        type=int,   default=2)
    args = parser.parse_args()

    # Cập nhật API URL
    global SHOPPING_ITEM_API
    if args.api_url:
        SHOPPING_ITEM_API = f"{args.api_url}/api/v1/shopping-item/create"

    # Lấy danh sách keyword
    keywords = args.keywords if args.keywords else load_keywords_from_file(args.file)

    # Tên file output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = args.output or f"shopee_batch_{timestamp}"

    print("🚀 Shopee Crawler - Multi Keyword")
    print(f"📋 Từ khóa ({len(keywords)}): {', '.join(keywords)}")
    print(f"📦 Số SP/keyword: {args.num}")
    print(f"💾 Output: {base_name}.{'csv/json' if args.format == 'both' else args.format}")

    driver = None
    all_products = []

    try:
        driver = build_driver(headless=args.headless, chrome_version=args.chrome_version)

        if not ensure_logged_in(driver, force_login=args.relogin,
                                headless=args.headless, debug=args.debug):
            print("\n❌ Không thể đăng nhập. Thoát.")
            return

        # Kiểm tra lần cuối
        driver.get(BASE)
        time.sleep(2)
        if "login" in driver.current_url:
            print("\n⚠️  Chưa đăng nhập, thử lại với --relogin")
            return

        # ── Crawl từng keyword ──
        print(f"\n{'='*60}")
        for idx, kw in enumerate(keywords, 1):
            print(f"\n[{idx}/{len(keywords)}] Keyword: '{kw}'")
            products = fetch_products(driver, kw, max_items=args.num, debug=args.debug)
            all_products.extend(products)

            # Nghỉ giữa các keyword (trừ keyword cuối)
            if idx < len(keywords):
                wait = args.delay + random.uniform(0, 2)
                print(f"  ⏳ Nghỉ {wait:.1f}s trước keyword tiếp theo...")
                time.sleep(wait)

        # ── Tổng kết ──
        print(f"\n{'='*60}")
        print(f"✅ TỔNG HỢP: {len(all_products)} sản phẩm từ {len(keywords)} keyword")

        # Thống kê theo keyword
        from collections import Counter
        counts = Counter(p["keyword"] for p in all_products)
        for kw, count in counts.items():
            print(f"  • '{kw}': {count} sản phẩm")
        print(f"{'='*60}")

        if not all_products:
            print("\n❌ Không lấy được sản phẩm nào!")
            return

        # ── Export file ──
        print()
        if args.format in ("csv", "both"):
            export_csv(all_products, Path(f"{base_name}.csv"))
        if args.format in ("json", "both"):
            export_json(all_products, Path(f"{base_name}.json"))

        # ── Gửi API ──
        if args.api:
            send_products_to_api(
                all_products, debug=args.debug,
                timeout=args.api_timeout, max_retries=args.api_retries
            )

    except KeyboardInterrupt:
        # Vẫn export phần đã crawl được nếu bị dừng giữa chừng
        print("\n\n🛑 Đã dừng giữa chừng!")
        if all_products:
            print(f"💾 Lưu {len(all_products)} sản phẩm đã crawl được...")
            if args.format in ("csv", "both"):
                export_csv(all_products, Path(f"{base_name}_partial.csv"))
            if args.format in ("json", "both"):
                export_json(all_products, Path(f"{base_name}_partial.json"))
    except Exception as e:
        print(f"\n❌ Lỗi: {e}")
        if args.debug:
            import traceback; traceback.print_exc()
        # Vẫn export nếu đã có dữ liệu
        if all_products:
            print(f"💾 Lưu {len(all_products)} sản phẩm đã có...")
            if args.format in ("csv", "both"):
                export_csv(all_products, Path(f"{base_name}_partial.csv"))
            if args.format in ("json", "both"):
                export_json(all_products, Path(f"{base_name}_partial.json"))
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()