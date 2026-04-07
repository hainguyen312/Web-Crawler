#!/usr/bin/env python3
"""
Tiki Crawler với Cookie Persistence - FIXED VERSION
- Sử dụng selector chính xác dựa trên cấu trúc HTML thực tế
- Xử lý srcset và các định dạng ảnh WebP
"""
import argparse
import json
import os
import random
import time
from pathlib import Path
from urllib.parse import quote_plus, urljoin
import re

from bs4 import BeautifulSoup
try:
    import undetected_chromedriver as uc
except ImportError:
    print("⚠️  Cần cài: pip install undetected-chromedriver beautifulsoup4")
    exit(1)

BASE = "https://tiki.vn"
COOKIE_FILE = Path.home() / ".tiki_cookies.json"


def build_driver(headless: bool = False):
    """Tạo undetected Chrome driver"""
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=vi-VN")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    if headless:
        options.add_argument("--headless=new")
    
    driver = uc.Chrome(options=options, version_main=None)
    return driver


def save_cookies(driver, filepath: Path):
    """Lưu cookies vào file"""
    cookies = driver.get_cookies()
    with open(filepath, 'w') as f:
        json.dump(cookies, f, indent=2)
    print(f"✅ Đã lưu cookies vào {filepath}")


def load_cookies(driver, filepath: Path):
    """Load cookies từ file"""
    if not filepath.exists():
        return False
    
    try:
        with open(filepath, 'r') as f:
            cookies = json.load(f)
        
        driver.get(BASE)
        time.sleep(2)
        
        for cookie in cookies:
            if 'expiry' in cookie:
                cookie['expiry'] = int(cookie['expiry'])
            driver.add_cookie(cookie)
        
        print("✅ Đã load cookies thành công")
        return True
    except Exception as e:
        print(f"⚠️  Lỗi khi load cookies: {e}")
        return False


def manual_login(driver):
    """Cho phép user đăng nhập thủ công"""
    print("\n" + "="*60)
    print("🔐 ĐĂNG NHẬP TIKI")
    print("="*60)
    print("1. Một cửa sổ Chrome đã mở")
    print("2. Vui lòng đăng nhập vào Tiki")
    print("3. Sau khi đăng nhập xong, nhấn Enter ở đây")
    print("="*60)
    
    driver.get(f"{BASE}/customer/account/login")
    
    input("\n⏸️  Nhấn Enter sau khi đã đăng nhập xong... ")
    
    driver.get(BASE)
    time.sleep(2)
    
    if "login" not in driver.current_url:
        print("✅ Đăng nhập thành công!")
        save_cookies(driver, COOKIE_FILE)
        return True
    else:
        print("❌ Chưa đăng nhập thành công")
        return False


def ensure_logged_in(driver, force_login: bool = False):
    """Đảm bảo đã đăng nhập vào Tiki"""
    
    if force_login:
        print("🔄 Bắt buộc đăng nhập lại...")
        if COOKIE_FILE.exists():
            COOKIE_FILE.unlink()
        return manual_login(driver)
    
    if COOKIE_FILE.exists():
        print("🍪 Tìm thấy cookies đã lưu, đang load...")
        if load_cookies(driver, COOKIE_FILE):
            driver.get(BASE)
            time.sleep(2)
            
            if "login" not in driver.current_url:
                print("✅ Cookie vẫn còn hiệu lực!")
                return True
            else:
                print("⚠️  Cookie đã hết hạn")
                COOKIE_FILE.unlink()
    
    return manual_login(driver)


def human_like_scroll(driver):
    """Cuộn trang giống người thật"""
    total_height = driver.execute_script("return document.body.scrollHeight")
    current_position = 0
    
    while current_position < total_height:
        scroll_amount = random.randint(300, 600)
        current_position += scroll_amount
        driver.execute_script(f"window.scrollTo(0, {current_position});")
        time.sleep(random.uniform(0.3, 0.7))
        total_height = driver.execute_script("return document.body.scrollHeight")


def scroll_infinite(driver, max_pages: int = 10):
    """Cuộn xuống để load thêm sản phẩm"""
    last_height = driver.execute_script("return document.body.scrollHeight")
    
    for i in range(max_pages):
        print(f"  📄 Đang load trang {i+1}/{max_pages}...")
        human_like_scroll(driver)
        time.sleep(random.uniform(2, 3))
        
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            print(f"  ✓ Đã load hết sản phẩm")
            break
        last_height = new_height


def extract_best_image_url(img_tag):
    """Trích xuất URL ảnh tốt nhất từ thẻ img"""
    # Thử srcset trước (chất lượng cao hơn)
    srcset = img_tag.get('srcset', '')
    if srcset:
        # srcset format: "url1 1x, url2 2x"
        # Lấy URL cuối cùng (thường là độ phân giải cao nhất)
        urls = re.findall(r'(https?://[^\s,]+)', srcset)
        if urls:
            return urls[-1]
    
    # Thử các attribute khác
    for attr in ['src', 'data-src', 'data-lazy-src']:
        url = img_tag.get(attr, '')
        if url and not url.startswith('data:'):
            if url.startswith('//'):
                return 'https:' + url
            return url
    
    return None


def fetch_products(driver, keyword: str, max_items: int = 30, debug: bool = False):
    """Crawl sản phẩm từ Tiki - VERSION 2.0"""
    search_url = f"{BASE}/search?q={quote_plus(keyword)}"
    
    print(f"\n🔍 Đang tìm kiếm: {keyword}")
    driver.get(search_url)
    time.sleep(random.uniform(3, 5))
    
    if "login" in driver.current_url:
        print("⚠️  Bị redirect sang trang login!")
        return []
    
    if debug:
        print(f"[DEBUG] URL hiện tại: {driver.current_url}")
    
    # Cuộn để load sản phẩm
    print("📜 Đang cuộn trang để load sản phẩm...")
    scroll_infinite(driver, max_pages=max(5, max_items // 15))
    
    time.sleep(3)
    
    # Parse HTML
    soup = BeautifulSoup(driver.page_source, "html.parser")
    results = []
    seen = set()
    
    if debug:
        # Lưu HTML để debug
        debug_file = "/tmp/tiki_debug.html"
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write(soup.prettify())
        print(f"[DEBUG] Đã lưu HTML vào {debug_file}")
    
    # STRATEGY 1: Tìm tất cả thẻ <a> có href chứa /p/
    product_links = soup.find_all('a', href=re.compile(r'/p/'))
    
    print(f"  🔎 Tìm thấy {len(product_links)} links sản phẩm")
    
    for a_tag in product_links:
        href = a_tag.get('href', '')
        if not href or '/p/' not in href:
            continue
        
        # Tạo product URL
        if href.startswith('/'):
            product_url = urljoin(BASE, href)
        else:
            product_url = href
        
        # Tìm ảnh trong cùng container với link
        # Có thể là child hoặc sibling
        img_tag = None
        
        # Thử tìm img trong chính thẻ a
        img_tag = a_tag.find('img')
        
        # Nếu không có, thử tìm trong parent
        if not img_tag and a_tag.parent:
            img_tag = a_tag.parent.find('img')
        
        # Thử tìm trong các div lân cận
        if not img_tag:
            parent = a_tag.parent
            for _ in range(3):  # Lên tối đa 3 cấp
                if not parent:
                    break
                img_tag = parent.find('img')
                if img_tag:
                    break
                parent = parent.parent
        
        if not img_tag:
            continue
        
        # Trích xuất URL ảnh
        img_url = extract_best_image_url(img_tag)
        
        if not img_url or img_url.startswith('data:'):
            continue
        
        # Kiểm tra trùng lặp
        key = (img_url, product_url)
        if key not in seen:
            seen.add(key)
            results.append(key)
            
            if debug and len(results) <= 3:
                print(f"[DEBUG {len(results)}] IMG: {img_url[:80]}...")
                print(f"[DEBUG {len(results)}] URL: {product_url}")
            
            if len(results) >= max_items:
                break
    
    # STRATEGY 2: Nếu không đủ, thử tìm theo class pattern
    if len(results) < max_items:
        print(f"  🔎 Strategy 2: Tìm theo pattern...")
        
        # Tìm các div có class chứa "product" hoặc "item"
        containers = soup.find_all(['div', 'article'], class_=re.compile(r'(product|item)', re.I))
        
        for container in containers:
            if len(results) >= max_items:
                break
            
            # Tìm link và ảnh trong container
            a_tag = container.find('a', href=re.compile(r'/p/'))
            img_tag = container.find('img')
            
            if not a_tag or not img_tag:
                continue
            
            href = a_tag.get('href', '')
            if not href:
                continue
            
            product_url = urljoin(BASE, href) if href.startswith('/') else href
            img_url = extract_best_image_url(img_tag)
            
            if not img_url or img_url.startswith('data:'):
                continue
            
            key = (img_url, product_url)
            if key not in seen:
                seen.add(key)
                results.append(key)
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Tiki Crawler với Cookie Persistence - FIXED"
    )
    parser.add_argument("keyword", help="Từ khóa tìm kiếm")
    parser.add_argument("-n", "--num", type=int, default=30, help="Số sản phẩm")
    parser.add_argument("--headless", action="store_true", help="Chạy ẩn")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    parser.add_argument("--relogin", action="store_true", help="Bắt buộc đăng nhập lại")
    args = parser.parse_args()
    
    print("🚀 Tiki Crawler - FIXED VERSION 2.0")
    print("="*60)
    
    driver = build_driver(headless=args.headless)
    
    try:
        # Đảm bảo đã đăng nhập
        if not ensure_logged_in(driver, force_login=args.relogin):
            print("\n❌ Không thể đăng nhập. Thoát chương trình.")
            return
        
        # Crawl sản phẩm
        pairs = fetch_products(driver, args.keyword, max_items=args.num, debug=args.debug)
        
        if not pairs:
            print("\n❌ Không lấy được sản phẩm nào!")
            print("💡 Các bước khắc phục:")
            print("   1. Thử chạy lại với --relogin")
            print("   2. Thử chạy với --debug để kiểm tra HTML")
            print("   3. Kiểm tra xem từ khóa có kết quả trên Tiki không")
            return
        
        # Hiển thị kết quả
        print(f"\n✅ Thành công! Lấy được {len(pairs)} sản phẩm\n")
        print("="*100)
        
        for i, (img, prod) in enumerate(pairs, 1):
            print(f"\n[{i:02d}]")
            print(f"  🖼️  {img}")
            print(f"  🔗 {prod}")
        
        print("\n" + "="*100)
        print(f"\n✨ Tổng: {len(pairs)} sản phẩm")
        
        # Tùy chọn: Lưu ra file JSON
        if pairs:
            output_file = f"tiki_{args.keyword}_{len(pairs)}.json"
            data = {
                "keyword": args.keyword,
                "total": len(pairs),
                "products": [
                    {"image": img, "url": prod}
                    for img, prod in pairs
                ]
            }
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"💾 Đã lưu vào: {output_file}")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Đã dừng")
    except Exception as e:
        print(f"\n❌ Lỗi: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
    finally:
        driver.quit()
        print("\n👋 Hoàn tất!\n")


if __name__ == "__main__":
    main()