"""Editor defaults and validation units; runtime billing uses saved model pricing."""

LLM_PRICING: dict[str, dict] = {
    # 官方高峰价；运行时仅使用管理员保存的配置，不按时间切换。
    # https://api-docs.deepseek.com/zh-cn/quick_start/pricing/ (2026-11-04)
    "deepseek-v4-pro": {"input_price_per_1m": 9.00, "cache_input_price_per_1m": 0.30, "output_price_per_1m": 27.00},
    "deepseek-flash": {"input_price_per_1m": 2.00, "cache_input_price_per_1m": 0.04, "output_price_per_1m": 8.00},
    "deepseek-v4-flash": {"input_price_per_1m": 2.00, "cache_input_price_per_1m": 0.04, "output_price_per_1m": 8.00},
    "glm-5.2": {"input_price_per_1m": 8.00, "output_price_per_1m": 28.00},
}

IMAGE_PRICING = {
    "seedream_5_5": {
        "type": "image", "currency": "CNY", "billing_unit": "pixel_tier",
        "prices": {"low": 0.13, "high_capped": 0.23},
        "input_image": {"first_free": 0, "price_per_image": 0.05},
    },
    "seedream_5_pro": {
        "type": "image", "currency": "CNY", "billing_unit": "pixel_tier",
        "prices": {"single_low": 0.30, "single_high": 0.60, "layer_low": 0.15, "layer_high": 0.30},
        "input_image": {"first_free": 1, "price_per_image": 0.02},
    },
}

VIDEO_PRICING: dict[str, dict] = {
    "seedance_2": {
        "type": "video",
        "currency": "CNY",
        "prices": {"480p": 46.00, "720p": 46.00, "1080p": 51.00, "4k": 26.00},
        "video_reference_prices": {"480p": 28.00, "720p": 28.00, "1080p": 31.00, "4k": 16.00},
    },
    "seedance_2_fast": {
        "type": "video",
        "currency": "CNY",
        "prices": {"480p": 37.00, "720p": 37.00},
        "video_reference_prices": {"480p": 22.00, "720p": 22.00},
    },
    "seedance_2_mini": {
        "type": "video",
        "currency": "CNY",
        "prices": {"480p": 23.00, "720p": 23.00},
        "video_reference_prices": {"480p": 14.00, "720p": 14.00},
    },
    "seedance_2_5": {
        "type": "video",
        "currency": "CNY",
        "prices": {"480p": 70.00, "720p": 70.00, "1080p": 77.00},
        "video_reference_prices": {"480p": 42.00, "720p": 42.00, "1080p": 46.00},
    },
    "minimax_h3": {
        "type": "video",
        "currency": "CNY",
        "billing_unit": "second",
        "prices": {"768P": 0.50, "2K": 0.80},
        "video_reference_prices": {"768P": 0.50, "2K": 0.80},
        "input_image": {"first_free": 5, "price_per_image": 0.20},
    },
    # AutoDL 峰谷价格由后台按实际合同填写，不套用官方 MiniMax 价格。
    "minimax_h3_autodl": {
        "type": "video",
        "currency": "CNY",
        "billing_unit": "second",
        "prices": {"480p": 0.0, "768p": 0.0},
        "video_reference_prices": {"480p": 0.0, "768p": 0.0},
    },
    # Wan 3 刊例价未随接口文档提供，先以零价档位初始化，由后台按实际合同价填写。
    "wan_3": {
        "type": "video",
        "currency": "CNY",
        "billing_unit": "second",
        "prices": {"480P": 0.0, "720P": 0.0, "1080P": 0.0},
        "video_reference_prices": {"480P": 0.0, "720P": 0.0, "1080P": 0.0},
    },
}

ASR_PRICING: dict[str, dict] = {
    "volc.seedasr.auc": {
        "type": "asr",
        "currency": "CNY",
        "billing_unit": "minute",
        "price_per_minute": 0.015,
    },
}
