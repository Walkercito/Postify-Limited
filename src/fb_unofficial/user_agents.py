import random
from typing import Final

_ANDROID_UAS: Final[tuple[str, ...]] = (
    "[FBAN/FB4A;FBAV/435.0.0.30.114;FBBV/515093674;FBDM/{density=2.625,width=1080,height=2400};FBLC/en_US;FBRV/517152755;FBCR/Verizon;FBMF/Google;FBBD/google;FBPN/com.facebook.katana;FBDV/Pixel 7;FBSV/13;FBOP/1;FBCA/arm64-v8a:null;]",
    "[FBAN/FB4A;FBAV/438.0.0.33.109;FBBV/520912345;FBDM/{density=3.0,width=1440,height=3120};FBLC/en_US;FBRV/521001234;FBCR/T-Mobile;FBMF/samsung;FBBD/samsung;FBPN/com.facebook.katana;FBDV/SM-S918U;FBSV/13;FBOP/1;FBCA/arm64-v8a:null;]",
    "[FBAN/FB4A;FBAV/441.0.0.37.111;FBBV/525501111;FBDM/{density=2.75,width=1080,height=2340};FBLC/en_US;FBRV/525600001;FBCR/AT&T;FBMF/OnePlus;FBBD/OnePlus;FBPN/com.facebook.katana;FBDV/CPH2449;FBSV/13;FBOP/1;FBCA/arm64-v8a:null;]",
)


def random_android_ua() -> str:
    return random.choice(_ANDROID_UAS)
