import argparse
import json
import time
from pathlib import Path
from typing import List, Dict, Any

import requests


BASE_URL = "https://stylid-dev.tipai.tech"
WARDROBE_ENDPOINT = f"{BASE_URL}/api/v1/ward-robe/create"


def read_image_urls(file_path: Path) -> List[str]:
    """Đọc danh sách URL ảnh từ file .txt, mỗi dòng 1 URL, bỏ qua dòng trống."""
    urls: List[str] = []
    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            url = line.strip()
            if url:
                urls.append(url)
    return urls


def analyze_wardrobe_image(image_url: str) -> Dict[str, Any]:
    """Gọi API phân tích wardrobe cho 1 URL ảnh."""
    payload = {"image": image_url}
    resp = requests.post(WARDROBE_ENDPOINT, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


def process_file(
    input_file: Path,
    output_file: Path,
    sleep_between_calls: float = 0.5,
) -> None:
    """
    Đọc URL từ file, gửi phân tích từng ảnh một.

    - input_file: file .txt chứa URL ảnh, mỗi dòng 1 URL
    - output_file: file .json để lưu toàn bộ kết quả
    - sleep_between_calls: số giây nghỉ giữa các lần gọi API
    """
    image_urls = read_image_urls(input_file)
    if not image_urls:
        print(f"Không tìm thấy URL nào trong file: {input_file}")
        return

    print(f"Đọc được {len(image_urls)} URL từ '{input_file}'.")
    print(f"Bắt đầu phân tích từng ảnh...")

    all_results: List[Dict[str, Any]] = []

    for idx, image_url in enumerate(image_urls, 1):
        print(f"[{idx}/{len(image_urls)}] Đang phân tích: {image_url[:60]}...")

        try:
            response = analyze_wardrobe_image(image_url)
        except requests.RequestException as e:
            print(f"  ❌ Lỗi khi gọi API: {e}")
            all_results.append(
                {
                    "image_url": image_url,
                    "status": "error",
                    "error": str(e),
                }
            )
            continue

        if (
            not isinstance(response, dict)
            or response.get("result") != "success"
        ):
            print(f"  ❌ Phản hồi không thành công: {response}")
            all_results.append(
                {
                    "image_url": image_url,
                    "status": "failed",
                    "response": response,
                }
            )
            continue

        data = response.get("data", [])
        print(f"  ✅ Thành công! Phát hiện {len(data)} item(s).")

        all_results.append(
            {
                "image_url": image_url,
                "status": "success",
                "response": response,
                "items_count": len(data),
            }
        )

        # Nghỉ giữa các lần gọi API
        if sleep_between_calls > 0 and idx < len(image_urls):
            time.sleep(sleep_between_calls)

    # Lưu toàn bộ kết quả ra file JSON
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    # Thống kê
    success_count = sum(1 for r in all_results if r.get("status") == "success")
    error_count = len(all_results) - success_count
    total_items = sum(r.get("items_count", 0) for r in all_results)

    print(f"\n{'='*60}")
    print(f"Hoàn thành! Đã lưu kết quả vào '{output_file}'.")
    print(f"Tổng số ảnh: {len(image_urls)}")
    print(f"Thành công: {success_count}")
    print(f"Lỗi: {error_count}")
    print(f"Tổng số items phát hiện: {total_items}")
    print(f"{'='*60}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Đọc URL ảnh từ file .txt và gọi API wardrobe analysis."
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default="downloads/o_sweater_urls.txt",
        help="Đường dẫn file .txt chứa URL ảnh (mặc định: downloads/o_sweater_urls.txt)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="downloads/wardrobe_analysis_result.json",
        help="File JSON để lưu kết quả (mặc định: downloads/wardrobe_analysis_result.json)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="Số giây nghỉ giữa các lần gọi API (mặc định: 0.5s)",
    )

    args = parser.parse_args()

    input_file = Path(args.input)
    output_file = Path(args.output)

    if not input_file.exists():
        print(f"File input không tồn tại: {input_file}")
        return

    process_file(
        input_file=input_file,
        output_file=output_file,
        sleep_between_calls=max(0.0, args.sleep),
    )


if __name__ == "__main__":
    main()

