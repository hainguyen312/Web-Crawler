#!/usr/bin/env python3
"""
FastAPI endpoints cho các web crawler:
- Pinterest Crawler
- Shopee Crawler  
- Tiki Crawler
"""
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Dict, Any
import asyncio
import traceback
import requests

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

# Import các crawler
from pinterestCrawler import InfinitePinterestCrawler, to_original_url, load_proxy_key
from shopeeCrawler import build_driver as build_shopee_driver, ensure_logged_in, fetch_products as fetch_shopee_products
from tikiCrawler import build_driver as build_tiki_driver, ensure_logged_in as ensure_tiki_logged_in, fetch_products as fetch_tiki_products

app = FastAPI(
    title="Web Crawler API",
    description="""
    API để crawl dữ liệu từ các website:
    
    * **Pinterest**: Crawl ảnh theo từ khóa
    * **Pinterest + Style Analysis**: Crawl ảnh từ Pinterest và gọi API style-analysis tuần tự cho từng ảnh
    * **Shopee**: Crawl sản phẩm và hình ảnh
    * **Tiki**: Crawl sản phẩm và hình ảnh
    
    ## Lưu ý quan trọng:
    
    * **Shopee & Tiki**: Cần đăng nhập lần đầu bằng script trực tiếp để lưu cookie
    * **Pinterest**: Có thể đăng nhập qua API hoặc dùng cookie đã lưu
    * **Style Analysis**: API style-analysis được gọi tuần tự, chờ response ảnh trước rồi mới gọi ảnh sau
    """,
    version="1.0.0",
    contact={
        "name": "Web Crawler API",
    },
    tags_metadata=[
        {
            "name": "Pinterest",
            "description": "Crawl ảnh từ Pinterest theo từ khóa tìm kiếm",
        },
        {
            "name": "Shopee",
            "description": "Crawl sản phẩm từ Shopee. **Lưu ý**: Cần đăng nhập lần đầu bằng script trực tiếp.",
        },
        {
            "name": "Tiki",
            "description": "Crawl sản phẩm từ Tiki. **Lưu ý**: Cần đăng nhập lần đầu bằng script trực tiếp.",
        },
        {
            "name": "Health",
            "description": "Health check endpoints",
        },
    ]
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Xử lý lỗi validation và trả về thông báo rõ ràng"""
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"] if loc != "body")
        msg = error["msg"]
        error_type = error["type"]
        errors.append(f"{field}: {msg} (type: {error_type})")
    
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Validation error",
            "errors": errors,
            "message": "Request body không hợp lệ. Vui lòng kiểm tra lại các trường."
        }
    )

# Thread pool để chạy các crawler (Selenium không async)
executor = ThreadPoolExecutor(max_workers=3)


class PinterestRequest(BaseModel):
    """Request model cho Pinterest crawler"""
    keyword: str = Field(
        ..., 
        description="Từ khóa tìm kiếm",
        example="sunset beach"
    )
    max_images: int = Field(
        20, 
        ge=1, 
        le=10000, 
        description="Số ảnh tối đa cần crawl. Crawler sẽ tự dừng khi đủ số ảnh này",
        example=20
    )
    max_pages: int = Field(
        30, 
        ge=1, 
        le=100000, 
        description="Số lần cuộn trang tối đa để load thêm ảnh. Có thể đặt số lớn, crawler sẽ tự dừng khi đủ max_images",
        example=30
    )
    email: Optional[str] = Field(
        None, 
        description="Email đăng nhập Pinterest (tùy chọn). Nếu không có, sẽ dùng cookie đã lưu hoặc crawl không đăng nhập",
        example="your_email@example.com"
    )
    password: Optional[str] = Field(
        None, 
        description="Password đăng nhập Pinterest (tùy chọn). Phải đi kèm với email",
        example="your_password"
    )
    headless: bool = Field(
        True, 
        description="Chạy browser ẩn (headless mode). Đặt False để xem browser",
        example=True
    )
    debug: bool = Field(
        False, 
        description="Bật chế độ debug để xem log chi tiết",
        example=False
    )
    cookies_path: str = Field(
        "cookies.pkl", 
        description="Đường dẫn file cookies để lưu/tải session",
        example="cookies.pkl"
    )
    proxy_key: Optional[str] = Field(
        None,
        description="Key proxy từ ckey.vn để tránh bị chặn IP (tùy chọn)",
        example="your_proxy_key"
    )
    proxy_nhamang: str = Field(
        "Random",
        description="Nhà mạng proxy: Random, Viettel, Vinaphone, fpt",
        example="Random"
    )
    proxy_tinhthanh: str = Field(
        "0",
        description="Tỉnh thành proxy: 0=Random, 3=Hà Nội, 6=Hồ Chí Minh, ...",
        example="0"
    )
    proxy_rotate_after: int = Field(
        50,
        ge=0,
        description="Số lần scroll trước khi tự động rotate proxy (0 để tắt auto rotate)",
        example=50
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "keyword": "hoa hồng",
                "max_images": 20,
                "max_pages": 30,
                "email": "your_email@example.com",
                "password": "your_password",
                "headless": True,
                "debug": False,
                "cookies_path": "cookies.pkl",
                "proxy_key": "your_proxy_key",
                "proxy_nhamang": "Random",
                "proxy_tinhthanh": "0",
                "proxy_rotate_after": 50
            }
        }


class PinterestResponse(BaseModel):
    """Response model cho Pinterest crawler"""
    keyword: str = Field(..., description="Từ khóa đã tìm kiếm", example="hoa hồng")
    total: int = Field(..., description="Tổng số ảnh đã crawl được", example=20)
    images: List[str] = Field(..., description="Danh sách URL ảnh đã được chuẩn hóa về originals", example=["https://i.pinimg.com/originals/...", "https://i.pinimg.com/originals/..."])
    message: str = Field(..., description="Thông báo kết quả", example="Thành công")
    
    class Config:
        json_schema_extra = {
            "example": {
                "keyword": "hoa hồng",
                "total": 20,
                "images": [
                    "https://i.pinimg.com/originals/3e/e0/f7/3ee0f71120cd51cdaadd085db9cb6dc2.jpg",
                    "https://i.pinimg.com/originals/6b/62/07/6b62072ff46ac092affbca0a96fdab59.jpg"
                ],
                "message": "Thành công"
            }
        }


class ShopeeRequest(BaseModel):
    """Request model cho Shopee crawler"""
    keyword: str = Field(
        ..., 
        description="Từ khóa tìm kiếm sản phẩm",
        example="điện thoại"
    )
    max_items: int = Field(
        30, 
        ge=1, 
        le=200, 
        description="Số sản phẩm tối đa cần crawl",
        example=30
    )
    headless: bool = Field(
        True, 
        description="Chạy browser ẩn (headless mode). **Lưu ý**: Phải có cookie đã lưu trước khi dùng headless=True",
        example=True
    )
    debug: bool = Field(
        False, 
        description="Bật chế độ debug để xem log chi tiết",
        example=False
    )
    relogin: bool = Field(
        False, 
        description="Bắt buộc đăng nhập lại. **Không hoạt động trong headless mode**. Dùng script trực tiếp để đăng nhập lại",
        example=False
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "keyword": "điện thoại",
                "max_items": 30,
                "headless": True,
                "debug": False,
                "relogin": False
            }
        }


class ProductItem(BaseModel):
    """Model cho một sản phẩm"""
    image_url: str = Field(..., description="URL hình ảnh sản phẩm", example="https://down-vn.img.susercontent.com/file/...")
    product_url: str = Field(..., description="URL trang sản phẩm", example="https://shopee.vn/...")


class ShopeeResponse(BaseModel):
    """Response model cho Shopee crawler"""
    keyword: str = Field(..., description="Từ khóa đã tìm kiếm", example="điện thoại")
    total: int = Field(..., description="Tổng số sản phẩm đã crawl được", example=30)
    products: List[ProductItem] = Field(..., description="Danh sách sản phẩm với URL ảnh và URL sản phẩm")
    message: str = Field(..., description="Thông báo kết quả", example="Thành công")
    
    class Config:
        json_schema_extra = {
            "example": {
                "keyword": "điện thoại",
                "total": 30,
                "products": [
                    {
                        "image_url": "https://down-vn.img.susercontent.com/file/vn-11134207-820l4-micwmeg81xjc37_tn.webp",
                        "product_url": "https://shopee.vn/Điện-Thoại-Itel-P55-8GB-256GB-NFC-5000-mAH-Sạc-Nhanh-45W-HD-90Hz-i.786178894.24593056744"
                    }
                ],
                "message": "Thành công"
            }
        }


class TikiRequest(BaseModel):
    """Request model cho Tiki crawler"""
    keyword: str = Field(
        ..., 
        description="Từ khóa tìm kiếm sản phẩm",
        example="laptop"
    )
    max_items: int = Field(
        30, 
        ge=1, 
        le=200, 
        description="Số sản phẩm tối đa cần crawl",
        example=30
    )
    headless: bool = Field(
        True, 
        description="Chạy browser ẩn (headless mode). **Lưu ý**: Phải có cookie đã lưu trước khi dùng headless=True",
        example=True
    )
    debug: bool = Field(
        False, 
        description="Bật chế độ debug để xem log chi tiết",
        example=False
    )
    relogin: bool = Field(
        False, 
        description="Bắt buộc đăng nhập lại. **Không hoạt động trong headless mode**. Dùng script trực tiếp để đăng nhập lại",
        example=False
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "keyword": "laptop",
                "max_items": 30,
                "headless": True,
                "debug": False,
                "relogin": False
            }
        }


class TikiResponse(BaseModel):
    """Response model cho Tiki crawler"""
    keyword: str = Field(..., description="Từ khóa đã tìm kiếm", example="laptop")
    total: int = Field(..., description="Tổng số sản phẩm đã crawl được", example=30)
    products: List[ProductItem] = Field(..., description="Danh sách sản phẩm với URL ảnh và URL sản phẩm")
    message: str = Field(..., description="Thông báo kết quả", example="Thành công")
    
    class Config:
        json_schema_extra = {
            "example": {
                "keyword": "laptop",
                "total": 30,
                "products": [
                    {
                        "image_url": "https://salt.tikicdn.com/cache/280x280/ts/product/...",
                        "product_url": "https://tiki.vn/laptop-..."
                    }
                ],
                "message": "Thành công"
            }
        }


class PinterestSearchAnalyzeRequest(BaseModel):
    """Request model cho Pinterest crawler kèm style analysis"""
    keyword: str = Field(
        ..., 
        description="Từ khóa tìm kiếm",
        example="sunset beach"
    )
    max_images: int = Field(
        20, 
        ge=1, 
        le=10000, 
        description="Số ảnh tối đa cần crawl. Crawler sẽ tự dừng khi đủ số ảnh này",
        example=20
    )
    max_pages: int = Field(
        30, 
        ge=1, 
        le=100000, 
        description="Số lần cuộn trang tối đa để load thêm ảnh. Có thể đặt số lớn, crawler sẽ tự dừng khi đủ max_images",
        example=30
    )
    platform: str = Field(
        "shopee",
        description="Platform để gửi trong API style-analysis",
        example="shopee"
    )
    email: Optional[str] = Field(
        None, 
        description="Email đăng nhập Pinterest (tùy chọn). Nếu không có, sẽ dùng cookie đã lưu hoặc crawl không đăng nhập",
        example="your_email@example.com"
    )
    password: Optional[str] = Field(
        None, 
        description="Password đăng nhập Pinterest (tùy chọn). Phải đi kèm với email",
        example="your_password"
    )
    headless: bool = Field(
        True, 
        description="Chạy browser ẩn (headless mode). Đặt False để xem browser",
        example=True
    )
    debug: bool = Field(
        False, 
        description="Bật chế độ debug để xem log chi tiết",
        example=False
    )
    cookies_path: str = Field(
        "cookies.pkl", 
        description="Đường dẫn file cookies để lưu/tải session",
        example="cookies.pkl"
    )
    proxy_key: Optional[str] = Field(
        None,
        description="Key proxy từ ckey.vn để tránh bị chặn IP (tùy chọn)",
        example="your_proxy_key"
    )
    proxy_nhamang: str = Field(
        "Random",
        description="Nhà mạng proxy: Random, Viettel, Vinaphone, fpt",
        example="Random"
    )
    proxy_tinhthanh: str = Field(
        "0",
        description="Tỉnh thành proxy: 0=Random, 3=Hà Nội, 6=Hồ Chí Minh, ...",
        example="0"
    )
    proxy_rotate_after: int = Field(
        50,
        ge=0,
        description="Số lần scroll trước khi tự động rotate proxy (0 để tắt auto rotate)",
        example=50
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "keyword": "hoa hồng",
                "max_images": 20,
                "max_pages": 30,
                "platform": "shopee",
                "email": "your_email@example.com",
                "password": "your_password",
                "headless": True,
                "debug": False,
                "cookies_path": "cookies.pkl",
                "proxy_key": "your_proxy_key",
                "proxy_nhamang": "Random",
                "proxy_tinhthanh": "0",
                "proxy_rotate_after": 50
            }
        }


class StyleAnalysisResult(BaseModel):
    """Model cho kết quả style analysis của một ảnh"""
    image_url: str = Field(..., description="URL ảnh đã được phân tích")
    success: bool = Field(..., description="Trạng thái thành công hay thất bại")
    analysis_data: Optional[Dict[str, Any]] = Field(None, description="Dữ liệu phân tích từ API")
    error_message: Optional[str] = Field(None, description="Thông báo lỗi nếu có")


class PinterestSearchAnalyzeResponse(BaseModel):
    """Response model cho Pinterest crawler kèm style analysis"""
    keyword: str = Field(..., description="Từ khóa đã tìm kiếm", example="hoa hồng")
    total_images: int = Field(..., description="Tổng số ảnh đã crawl được", example=20)
    total_analyzed: int = Field(..., description="Tổng số ảnh đã phân tích thành công", example=18)
    total_failed: int = Field(..., description="Tổng số ảnh phân tích thất bại", example=2)
    results: List[StyleAnalysisResult] = Field(..., description="Danh sách kết quả phân tích cho từng ảnh")
    message: str = Field(..., description="Thông báo kết quả", example="Thành công")
    
    class Config:
        json_schema_extra = {
            "example": {
                "keyword": "hoa hồng",
                "total_images": 20,
                "total_analyzed": 18,
                "total_failed": 2,
                "results": [
                    {
                        "image_url": "https://i.pinimg.com/originals/...",
                        "success": True,
                        "analysis_data": {...},
                        "error_message": None
                    }
                ],
                "message": "Thành công"
            }
        }


def run_pinterest_crawler(
    keyword: str,
    max_images: int,
    max_pages: int,
    email: Optional[str],
    password: Optional[str],
    headless: bool,
    debug: bool,
    cookies_path: str,
    proxy_key: Optional[str] = None,
    proxy_nhamang: str = "Random",
    proxy_tinhthanh: str = "0",
    proxy_rotate_after: int = 50
) -> List[str]:
    """Chạy Pinterest crawler trong thread pool"""
    print(f"\n[API] === Bắt đầu Pinterest Crawler ===")
    print(f"[API] Keyword: {keyword}")
    print(f"[API] Max images: {max_images}")
    print(f"[API] Max pages: {max_pages}")
    print(f"[API] Headless: {headless}")
    print(f"[API] Debug: {debug}")
    
    # Tự động load proxy key nếu không được cung cấp
    if not proxy_key:
        proxy_key = load_proxy_key()
        if proxy_key:
            print(f"[API] Đã tự động load proxy key từ file hoặc environment variable")
    
    crawler = None
    try:
        print("[API] Khởi tạo crawler...")
        crawler = InfinitePinterestCrawler(
            headless=headless,
            cookies_path=cookies_path,
            proxy_key=proxy_key,
            proxy_nhamang=proxy_nhamang,
            proxy_tinhthanh=proxy_tinhthanh,
            proxy_rotate_after=proxy_rotate_after
        )
        print("[API] Crawler đã sẵn sàng")
        
        # Kiểm tra login
        print("[API] Kiểm tra đăng nhập...")
        if crawler.is_logged_in():
            print("[API] Đã đăng nhập sẵn bằng cookies.")
        elif email and password:
            print("[API] Đang đăng nhập bằng email/password...")
            ok = crawler.login(email, password, debug=debug)
            if ok:
                print("[API] Đăng nhập thành công.")
            elif debug:
                print("[API] Đăng nhập thất bại, tiếp tục crawl không đăng nhập.")
        else:
            print("[API] Không có thông tin đăng nhập, crawl không đăng nhập.")
        
        print(f"[API] Mở trang tìm kiếm: {keyword}")
        crawler.open_search(keyword)
        
        print(f"[API] Bắt đầu crawl...")
        urls = crawler.crawl(max_images=max_images, max_pages=max_pages, debug=debug)
        
        # Chuẩn hóa URL về originals
        normalized_urls = [to_original_url(url) for url in urls]
        print(f"[API] Crawl hoàn tất: {len(normalized_urls)} ảnh")
        return normalized_urls
    except Exception as e:
        print(f"\n[API ERROR] Lỗi trong quá trình crawl Pinterest:")
        print(f"[API ERROR] {type(e).__name__}: {str(e)}")
        traceback.print_exc()
        raise
    finally:
        if crawler:
            try:
                print("[API] Đóng crawler...")
                crawler.close()
                print("[API] Crawler đã đóng")
            except Exception as e:
                print(f"[API WARNING] Lỗi khi đóng crawler: {e}")


def run_shopee_crawler(
    keyword: str,
    max_items: int,
    headless: bool,
    debug: bool,
    relogin: bool
) -> List[tuple]:
    """Chạy Shopee crawler trong thread pool"""
    from pathlib import Path
    
    print(f"\n[API] === Bắt đầu Shopee Crawler ===")
    print(f"[API] Keyword: {keyword}")
    print(f"[API] Max items: {max_items}")
    print(f"[API] Headless: {headless}")
    print(f"[API] Debug: {debug}")
    
    # Kiểm tra cookie trước khi khởi tạo driver
    cookie_file = Path.home() / ".shopee_cookies.json"
    
    # Nếu headless=True và không có cookie, không thể đăng nhập thủ công
    if headless and not cookie_file.exists():
        raise Exception(
            "Không có cookie đã lưu. Vui lòng chạy script shopeeCrawler.py trực tiếp "
            "lần đầu để đăng nhập (cookie sẽ được lưu tự động), sau đó mới dùng API."
        )
    
    # Nếu headless=True và force relogin, không thể đăng nhập thủ công
    if headless and relogin:
        raise Exception(
            "Không thể đăng nhập lại trong headless mode. "
            "Vui lòng chạy script shopeeCrawler.py với --relogin để đăng nhập lại."
        )
    
    driver = None
    try:
        print("[API] Khởi tạo driver...")
        driver = build_shopee_driver(headless=headless)
        print("[API] Driver đã sẵn sàng")
        
        # Monkey patch builtins.input() và manual_login để tránh block khi chạy trong API
        import builtins
        import shopeeCrawler

        original_input = builtins.input
        original_manual_login = getattr(shopeeCrawler, "manual_login", None)

        def mock_input(prompt=""):
            raise Exception(
                "Đăng nhập thủ công không được hỗ trợ qua API. "
                "Vui lòng chạy script shopeeCrawler.py trực tiếp để đăng nhập lần đầu."
            )

        def mock_manual_login(driver):
            raise Exception(
                "Không thể dùng manual_login trong headless/API. "
                "Có thể cookie đã hỏng hoặc hết hạn. "
                "Vui lòng xóa ~/.shopee_cookies.json và chạy: "
                "python shopeeCrawler.py \"<keyword>\" --headless=false --relogin"
            )

        builtins.input = mock_input
        if original_manual_login is not None:
            shopeeCrawler.manual_login = mock_manual_login

        try:
            print("[API] Kiểm tra đăng nhập...")
            if not ensure_logged_in(driver, force_login=relogin):
                raise Exception("Không thể đăng nhập vào Shopee. Cookie có thể đã hết hạn.")
            
            print("[API] Đã đăng nhập thành công")
            print(f"[API] Bắt đầu crawl sản phẩm...")
            
            pairs = fetch_shopee_products(driver, keyword, max_items=max_items, debug=True)
            
            print(f"[API] Crawl hoàn tất: {len(pairs)} sản phẩm")
            return pairs
            
        except Exception as e:
            print(f"\n[API ERROR] Lỗi trong quá trình crawl:")
            print(f"[API ERROR] {type(e).__name__}: {str(e)}")
            print(f"[API ERROR] Traceback:")
            traceback.print_exc()
            raise
        finally:
            # Khôi phục input/manual_login gốc
            builtins.input = original_input
            if original_manual_login is not None:
                shopeeCrawler.manual_login = original_manual_login
                
    except Exception as e:
        print(f"\n[API ERROR] Lỗi khởi tạo driver:")
        print(f"[API ERROR] {type(e).__name__}: {str(e)}")
        traceback.print_exc()
        raise
    finally:
        if driver:
            try:
                print("[API] Đóng driver...")
                driver.quit()
                print("[API] Driver đã đóng")
            except Exception as e:
                print(f"[API WARNING] Lỗi khi đóng driver: {e}")


def run_tiki_crawler(
    keyword: str,
    max_items: int,
    headless: bool,
    debug: bool,
    relogin: bool
) -> List[tuple]:
    """Chạy Tiki crawler trong thread pool"""
    from pathlib import Path
    
    # Kiểm tra cookie trước khi khởi tạo driver
    cookie_file = Path.home() / ".tiki_cookies.json"
    
    # Nếu headless=True và không có cookie, không thể đăng nhập thủ công
    if headless and not cookie_file.exists():
        raise Exception(
            "Không có cookie đã lưu. Vui lòng chạy script tikiCrawler.py trực tiếp "
            "lần đầu để đăng nhập (cookie sẽ được lưu tự động), sau đó mới dùng API."
        )
    
    # Nếu headless=True và force relogin, không thể đăng nhập thủ công
    if headless and relogin:
        raise Exception(
            "Không thể đăng nhập lại trong headless mode. "
            "Vui lòng chạy script tikiCrawler.py với --relogin để đăng nhập lại."
        )
    
    driver = build_tiki_driver(headless=headless)
    try:
        # Monkey patch builtins.input() và manual_login để tránh block khi chạy trong API
        import builtins
        import tikiCrawler

        original_input = builtins.input
        original_manual_login = getattr(tikiCrawler, "manual_login", None)

        def mock_input(prompt=""):
            raise Exception(
                "Đăng nhập thủ công không được hỗ trợ qua API. "
                "Vui lòng chạy script tikiCrawler.py trực tiếp để đăng nhập lần đầu."
            )

        def mock_manual_login(driver):
            raise Exception(
                "Không thể dùng manual_login trong headless/API. "
                "Có thể cookie đã hỏng hoặc hết hạn. "
                "Vui lòng xóa ~/.tiki_cookies.json và chạy: "
                "python tikiCrawler.py \"<keyword>\" --headless=false --relogin"
            )

        builtins.input = mock_input
        if original_manual_login is not None:
            tikiCrawler.manual_login = mock_manual_login

        try:
            if not ensure_tiki_logged_in(driver, force_login=relogin):
                raise Exception("Không thể đăng nhập vào Tiki. Cookie có thể đã hết hạn.")

            pairs = fetch_tiki_products(driver, keyword, max_items=max_items, debug=debug)
            return pairs
        finally:
            # Khôi phục input/manual_login gốc
            builtins.input = original_input
            if original_manual_login is not None:
                tikiCrawler.manual_login = original_manual_login
    finally:
        driver.quit()


def call_style_analysis_api(image_url: str, platform: str, debug: bool = False) -> Dict[str, Any]:
    """
    Gọi API style-analysis cho một ảnh.
    Trả về dict chứa success, analysis_data (nếu thành công) hoặc error_message (nếu thất bại).
    """
    api_url = "https://stylid-dev.tipai.tech/api/v1/style-analysis/create"
    payload = {
        "image": image_url,
        "linkAffililate": "",
        "platform": platform
    }
    
    try:
        if debug:
            print(f"[STYLE-API] Đang gọi API cho ảnh: {image_url[:80]}...")
        
        response = requests.post(api_url, json=payload, timeout=60)
        
        if response.status_code == 200:
            data = response.json()
            if debug:
                print(f"[STYLE-API] Thành công cho ảnh: {image_url[:80]}...")
            return {
                "success": True,
                "analysis_data": data,
                "error_message": None
            }
        else:
            error_msg = f"API trả về status {response.status_code}: {response.text[:200]}"
            if debug:
                print(f"[STYLE-API] Lỗi: {error_msg}")
            return {
                "success": False,
                "analysis_data": None,
                "error_message": error_msg
            }
    except requests.exceptions.RequestException as e:
        error_msg = f"Lỗi kết nối API: {str(e)}"
        if debug:
            print(f"[STYLE-API] Lỗi: {error_msg}")
        return {
            "success": False,
            "analysis_data": None,
            "error_message": error_msg
        }
    except Exception as e:
        error_msg = f"Lỗi không xác định: {str(e)}"
        if debug:
            print(f"[STYLE-API] Lỗi: {error_msg}")
        return {
            "success": False,
            "analysis_data": None,
            "error_message": error_msg
        }


def run_pinterest_crawl_and_analyze(
    keyword: str,
    max_images: int,
    max_pages: int,
    platform: str,
    email: Optional[str],
    password: Optional[str],
    headless: bool,
    debug: bool,
    cookies_path: str,
    proxy_key: Optional[str] = None,
    proxy_nhamang: str = "Random",
    proxy_tinhthanh: str = "0",
    proxy_rotate_after: int = 50
) -> List[Dict[str, Any]]:
    """
    Crawl ảnh từ Pinterest rồi gọi API style-analysis tuần tự cho từng ảnh.
    Trả về list các dict chứa kết quả phân tích.
    """
    print(f"\n[API] === Bắt đầu Pinterest Crawl và Analyze ===")
    print(f"[API] Keyword: {keyword}")
    print(f"[API] Max images: {max_images}")
    print(f"[API] Platform: {platform}")
    
    # Bước 1: Crawl ảnh từ Pinterest
    print(f"\n[API] === Bước 1: Crawl ảnh từ Pinterest ===")
    image_urls = run_pinterest_crawler(
        keyword=keyword,
        max_images=max_images,
        max_pages=max_pages,
        email=email,
        password=password,
        headless=headless,
        debug=debug,
        cookies_path=cookies_path,
        proxy_key=proxy_key,
        proxy_nhamang=proxy_nhamang,
        proxy_tinhthanh=proxy_tinhthanh,
        proxy_rotate_after=proxy_rotate_after
    )
    
    if not image_urls:
        print("[API] Không có ảnh nào để phân tích.")
        return []
    
    print(f"[API] Đã crawl được {len(image_urls)} ảnh.")
    
    # Bước 2: Gọi API style-analysis tuần tự cho từng ảnh
    print(f"\n[API] === Bước 2: Phân tích style tuần tự cho từng ảnh ===")
    results = []
    
    for idx, image_url in enumerate(image_urls, 1):
        print(f"[API] [{idx}/{len(image_urls)}] Đang phân tích ảnh...")
        
        analysis_result = call_style_analysis_api(
            image_url=image_url,
            platform=platform,
            debug=debug
        )
        
        result = {
            "image_url": image_url,
            "success": analysis_result["success"],
            "analysis_data": analysis_result["analysis_data"],
            "error_message": analysis_result["error_message"]
        }
        results.append(result)
        
        if analysis_result["success"]:
            print(f"[API] [{idx}/{len(image_urls)}] ✓ Thành công")
        else:
            print(f"[API] [{idx}/{len(image_urls)}] ✗ Thất bại: {analysis_result['error_message']}")
    
    print(f"\n[API] === Hoàn tất phân tích ===")
    print(f"[API] Tổng số ảnh: {len(results)}")
    print(f"[API] Thành công: {sum(1 for r in results if r['success'])}")
    print(f"[API] Thất bại: {sum(1 for r in results if not r['success'])}")
    
    return results


@app.get("/")
async def root():
    """Endpoint root"""
    return {
        "message": "Web Crawler API",
        "endpoints": {
            "pinterest": "/api/pinterest/search",
            "pinterest_search_and_analyze": "/api/pinterest/search-and-analyze",
            "shopee": "/api/shopee/search",
            "tiki": "/api/tiki/search"
        },
        "docs": "/docs"
    }


@app.post("/api/pinterest/search", response_model=PinterestResponse, tags=["Pinterest"])
async def search_pinterest(request: PinterestRequest):
    """
    Crawl ảnh từ Pinterest theo từ khóa tìm kiếm.
    
    **Tính năng:**
    - Tìm kiếm ảnh theo từ khóa
    - Tự động cuộn trang để load thêm ảnh
    - Chuẩn hóa URL về chất lượng gốc (originals)
    - Hỗ trợ đăng nhập bằng email/password hoặc dùng cookie đã lưu
    
    **Lưu ý:**
    - Nếu không có email/password, sẽ dùng cookie đã lưu (nếu có)
    - Có thể crawl không đăng nhập nhưng số lượng ảnh có thể bị giới hạn
    """
    try:
        loop = asyncio.get_event_loop()
        urls = await loop.run_in_executor(
            executor,
            run_pinterest_crawler,
            request.keyword,
            request.max_images,
            request.max_pages,
            request.email,
            request.password,
            request.headless,
            request.debug,
            request.cookies_path,
            request.proxy_key,
            request.proxy_nhamang,
            request.proxy_tinhthanh,
            request.proxy_rotate_after
        )
        
        if not urls:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy ảnh nào. Có thể Pinterest yêu cầu đăng nhập hoặc từ khóa không có kết quả."
            )
        
        return PinterestResponse(
            keyword=request.keyword,
            total=len(urls),
            images=urls,
            message="Thành công"
        )
    except Exception as e:
        error_detail = f"Lỗi khi crawl Pinterest: {str(e)}"
        if request.debug:
            error_detail += f"\n\nTraceback:\n{traceback.format_exc()}"
        print(f"[API ERROR] {error_detail}")
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/api/shopee/search", response_model=ShopeeResponse, tags=["Shopee"])
async def search_shopee(request: ShopeeRequest):
    """
    Crawl sản phẩm từ Shopee theo từ khóa tìm kiếm.
    
    **Tính năng:**
    - Tìm kiếm sản phẩm theo từ khóa
    - Lấy URL ảnh và URL sản phẩm
    - Tự động cuộn trang để load thêm sản phẩm
    
    **⚠️ QUAN TRỌNG - Đăng nhập:**
    - **Lần đầu tiên**: Phải chạy script `shopeeCrawler.py` trực tiếp để đăng nhập
      ```bash
      python shopeeCrawler.py "điện thoại" --headless=false
      ```
    - Cookie sẽ được lưu tự động tại `~/.shopee_cookies.json`
    - **Sau đó**: Mới có thể dùng API với `headless=True`
    - Nếu chạy API với `headless=True` mà chưa có cookie → sẽ báo lỗi rõ ràng
    """
    try:
        loop = asyncio.get_event_loop()
        pairs = await loop.run_in_executor(
            executor,
            run_shopee_crawler,
            request.keyword,
            request.max_items,
            request.headless,
            request.debug,
            request.relogin
        )
        
        if not pairs:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy sản phẩm nào. Có thể cần đăng nhập lại với --relogin=True"
            )
        
        products = [
            ProductItem(image_url=img, product_url=prod)
            for img, prod in pairs
        ]
        
        return ShopeeResponse(
            keyword=request.keyword,
            total=len(products),
            products=products,
            message="Thành công"
        )
    except Exception as e:
        error_detail = f"Lỗi khi crawl Shopee: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(error_detail)
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/api/tiki/search", response_model=TikiResponse, tags=["Tiki"])
async def search_tiki(request: TikiRequest):
    """
    Crawl sản phẩm từ Tiki theo từ khóa tìm kiếm.
    
    **Tính năng:**
    - Tìm kiếm sản phẩm theo từ khóa
    - Lấy URL ảnh và URL sản phẩm
    - Tự động cuộn trang để load thêm sản phẩm
    
    **⚠️ QUAN TRỌNG - Đăng nhập:**
    - **Lần đầu tiên**: Phải chạy script `tikiCrawler.py` trực tiếp để đăng nhập
      ```bash
      python tikiCrawler.py "laptop" --headless=false
      ```
    - Cookie sẽ được lưu tự động tại `~/.tiki_cookies.json`
    - **Sau đó**: Mới có thể dùng API với `headless=True`
    - Nếu chạy API với `headless=True` mà chưa có cookie → sẽ báo lỗi rõ ràng
    """
    try:
        loop = asyncio.get_event_loop()
        pairs = await loop.run_in_executor(
            executor,
            run_tiki_crawler,
            request.keyword,
            request.max_items,
            request.headless,
            request.debug,
            request.relogin
        )
        
        if not pairs:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy sản phẩm nào. Có thể cần đăng nhập lại với relogin=True"
            )
        
        products = [
            ProductItem(image_url=img, product_url=prod)
            for img, prod in pairs
        ]
        
        return TikiResponse(
            keyword=request.keyword,
            total=len(products),
            products=products,
            message="Thành công"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi crawl Tiki: {str(e)}")


@app.post("/api/pinterest/search-and-analyze", response_model=PinterestSearchAnalyzeResponse, tags=["Pinterest"])
async def search_pinterest_and_analyze(request: PinterestSearchAnalyzeRequest):
    """
    Crawl ảnh từ Pinterest theo từ khóa, sau đó gọi API style-analysis tuần tự cho từng ảnh.
    
    **Tính năng:**
    - Tìm kiếm ảnh theo từ khóa trên Pinterest
    - Tự động cuộn trang để load thêm ảnh
    - Chuẩn hóa URL về chất lượng gốc (originals)
    - Gọi API style-analysis tuần tự cho từng ảnh (chờ response ảnh trước rồi mới gọi ảnh sau)
    - Hỗ trợ đăng nhập bằng email/password hoặc dùng cookie đã lưu
    
    **Lưu ý:**
    - Nếu không có email/password, sẽ dùng cookie đã lưu (nếu có)
    - Có thể crawl không đăng nhập nhưng số lượng ảnh có thể bị giới hạn
    - API style-analysis được gọi tuần tự, không song song
    - Platform có thể là: shopee, lazada, tiki, sendo, amazon
    """
    try:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            executor,
            run_pinterest_crawl_and_analyze,
            request.keyword,
            request.max_images,
            request.max_pages,
            request.platform,
            request.email,
            request.password,
            request.headless,
            request.debug,
            request.cookies_path,
            request.proxy_key,
            request.proxy_nhamang,
            request.proxy_tinhthanh,
            request.proxy_rotate_after
        )
        
        if not results:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy ảnh nào để phân tích. Có thể Pinterest yêu cầu đăng nhập hoặc từ khóa không có kết quả."
            )
        
        # Chuyển đổi results sang StyleAnalysisResult
        analysis_results = [
            StyleAnalysisResult(
                image_url=r["image_url"],
                success=r["success"],
                analysis_data=r.get("analysis_data"),
                error_message=r.get("error_message")
            )
            for r in results
        ]
        
        total_analyzed = sum(1 for r in results if r["success"])
        total_failed = len(results) - total_analyzed
        
        return PinterestSearchAnalyzeResponse(
            keyword=request.keyword,
            total_images=len(results),
            total_analyzed=total_analyzed,
            total_failed=total_failed,
            results=analysis_results,
            message="Thành công"
        )
    except Exception as e:
        error_detail = f"Lỗi khi crawl và phân tích Pinterest: {str(e)}"
        if request.debug:
            error_detail += f"\n\nTraceback:\n{traceback.format_exc()}"
        print(f"[API ERROR] {error_detail}")
        raise HTTPException(status_code=500, detail=error_detail)


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint để kiểm tra trạng thái API.
    
    **Response:**
    - `status: "healthy"` - API đang hoạt động bình thường
    """
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)