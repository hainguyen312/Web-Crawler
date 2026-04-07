import asyncio
from playwright.async_api import async_playwright
import os
import requests
import time
import re


def convert_to_high_quality_url(url):
    """Chuyển đổi URL sang phiên bản chất lượng cao nhất"""
    if 'pinimg.com' not in url:
        return url

    # Loại bỏ các size nhỏ và chuyển sang originals
    url = re.sub(r'/(236x|474x|564x|736x|1200x)/', '/originals/', url)

    # Loại bỏ query parameters (resize, crop, etc.)
    url = url.split('?')[0]

    return url


async def capture_images_from_pinterest(url, scroll_count=5, max_images=100):
    async with async_playwright() as p:
        # Hiển thị browser để debug
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # Lưu trữ URL hình ảnh
        image_urls = set()
        original_urls = set()  # URLs đã convert sang originals

        # Chức năng xử lý response để lấy ảnh chất lượng cao
        def handle_response(response):
            if response.request.resource_type == 'image':
                url = response.url

                # Chỉ lấy ảnh từ Pinterest CDN
                if 'pinimg.com' in url:
                    # Bỏ qua avatar, profile pics
                    if any(x in url.lower() for x in ['avatar', 'user', 'profile', '75x75', '30x30']):
                        return

                    # Chấp nhận nhiều định dạng ảnh
                    if any(url.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                        # Chuyển sang URL chất lượng cao
                        high_quality_url = convert_to_high_quality_url(url)
                        original_urls.add(high_quality_url)
                        image_urls.add(url)  # Giữ URL gốc để so sánh

                        if len(original_urls) % 10 == 0:
                            print(
                                f"  → Đã phát hiện {len(original_urls)} ảnh chất lượng cao...")

        # Đăng ký listener
        page.on('response', handle_response)

        # Điều hướng đến URL
        print(f"\n{'='*60}")
        print(f"Đang truy cập: {url}")
        print(f"{'='*60}\n")
        await page.goto(url, wait_until='networkidle')

        # Chờ trang tải
        await page.wait_for_timeout(3000)

        # Cuộn trang nhiều lần để tải thêm ảnh
        for i in range(scroll_count):
            if len(original_urls) >= max_images:
                print(f"\n✓ Đã đủ {max_images} ảnh, dừng cuộn.")
                break

            print(f"\nCuộn lần {i + 1}/{scroll_count}...")

            # Lấy chiều cao hiện tại của trang
            previous_height = await page.evaluate('document.body.scrollHeight')

            # Cuộn xuống cuối trang
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')

            # Chờ nội dung mới tải
            await page.wait_for_timeout(2000)

            # Kiểm tra xem có nội dung mới không
            new_height = await page.evaluate('document.body.scrollHeight')

            print(f"  → Đã tìm thấy {len(original_urls)} ảnh chất lượng cao")

            # Nếu không có nội dung mới, dừng cuộn
            if new_height == previous_height:
                print("\n⚠ Đã đến cuối trang hoặc không có thêm nội dung mới.")
                break

        # Chờ thêm một chút để đảm bảo tất cả ảnh đã tải
        await page.wait_for_timeout(2000)

        # Lấy thêm URLs từ page source nếu cần
        print("\n→ Đang trích xuất thêm URLs từ page source...")
        page_content = await page.content()

        # Tìm thêm URLs trong HTML
        pattern = r'https://i\.pinimg\.com/(?:originals|1200x|736x|564x)/[a-zA-Z0-9/_.-]+'
        additional_urls = re.findall(pattern, page_content)

        for url in additional_urls:
            if 'pinimg.com' in url and not any(x in url.lower() for x in ['avatar', 'user', 'profile']):
                high_quality_url = convert_to_high_quality_url(url)
                original_urls.add(high_quality_url)

        # Đóng trình duyệt
        await browser.close()

        print(f"\n{'='*60}")
        print(f"✓ TỔNG SỐ ẢNH CHẤT LƯỢNG CAO: {len(original_urls)}")
        print(f"{'='*60}\n")

        return list(original_urls)


def download_images(image_urls, keyword, save_dir='pinterest_images'):
    """Download ảnh về máy"""
    if not image_urls:
        print("\n✗ Không có URL nào để tải!")
        return

    # Tạo thư mục
    keyword_dir = os.path.join(save_dir, keyword.replace(' ', '_'))
    os.makedirs(keyword_dir, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"BẮT ĐẦU TẢI {len(image_urls)} ẢNH CHẤT LƯỢNG CAO")
    print(f"{'='*60}\n")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.pinterest.com/'
    }

    downloaded = 0
    skipped = 0
    errors = 0

    for idx, url in enumerate(image_urls, 1):
        try:
            print(f"[{idx}/{len(image_urls)}] Đang tải: {url[:70]}...")

            response = requests.get(url, headers=headers, timeout=20)

            if response.status_code == 200:
                file_size = len(response.content)

                # Kiểm tra kích thước - chỉ bỏ qua nếu quá nhỏ (< 5KB)
                if file_size < 5000:
                    print(
                        f"    ⊘ Bỏ qua: kích thước quá nhỏ ({file_size} bytes)")
                    skipped += 1
                    continue

                # Xác định extension
                ext = 'jpg'
                content_type = response.headers.get('content-type', '')

                if '.png' in url or 'image/png' in content_type:
                    ext = 'png'
                elif '.gif' in url or 'image/gif' in content_type:
                    ext = 'gif'
                elif '.webp' in url or 'image/webp' in content_type:
                    ext = 'webp'

                filename = os.path.join(
                    keyword_dir, f'{keyword}_{downloaded+1}.{ext}')

                with open(filename, 'wb') as f:
                    f.write(response.content)

                downloaded += 1

                # Hiển thị kích thước
                if file_size >= 1024*1024:
                    size_str = f"{file_size/(1024*1024):.2f} MB"
                else:
                    size_str = f"{file_size/1024:.1f} KB"

                print(
                    f"    ✓ Đã lưu: {os.path.basename(filename)} ({size_str})")

            elif response.status_code == 404:
                print(f"    ✗ Không tìm thấy ảnh (404)")
                errors += 1
            else:
                print(f"    ✗ Lỗi HTTP {response.status_code}")
                errors += 1

            time.sleep(0.3)  # Delay nhỏ tránh bị chặn

        except Exception as e:
            print(f"    ✗ Lỗi: {str(e)[:50]}")
            errors += 1

    print(f"\n{'='*60}")
    print(f"KẾT QUẢ:")
    print(f"  ✓ Đã tải thành công: {downloaded} ảnh")
    print(f"  ⊘ Bỏ qua (kích thước nhỏ): {skipped} ảnh")
    print(f"  ✗ Lỗi: {errors} ảnh")
    print(f"  📁 Thư mục: {os.path.abspath(keyword_dir)}")
    print(f"{'='*60}")


async def main(query, scroll_count=10, max_images=100):
    """Hàm chính"""
    print(f"\n{'='*60}")
    print(f"PINTEREST IMAGE CRAWLER - HIGH QUALITY")
    print(f"Từ khóa: '{query}'")
    print(f"Số lượng mục tiêu: {max_images} ảnh")
    print(f"Số lần cuộn tối đa: {scroll_count}")
    print(f"{'='*60}\n")

    url = f"https://www.pinterest.com/search/pins/?q={query}"

    # Lấy danh sách URLs chất lượng cao
    images = await capture_images_from_pinterest(url, scroll_count, max_images)

    if images:
        # Hiển thị 3 URL mẫu
        print("URL mẫu (3 ảnh đầu):")
        for i, img_url in enumerate(images[:3], 1):
            print(f"  {i}. {img_url}")

        # Download ảnh
        download_images(images, query)
    else:
        print("\n✗ Không tìm thấy ảnh nào!")


# Chạy chức năng chính
if __name__ == "__main__":
    # Cấu hình
    query = input(
        "Nhập từ khóa tìm kiếm (hoặc Enter để dùng 'outfit men'): ").strip()
    if not query:
        query = 'outfit women'

    try:
        max_images = int(
            input("Số lượng ảnh muốn tải (mặc định 100): ") or "100")
    except:
        max_images = 10

    try:
        scroll_count = int(input("Số lần cuộn tối đa (mặc định 20): ") or "20")
    except:
        scroll_count = 2

    # Chạy
    asyncio.run(main(query, scroll_count, max_images))
