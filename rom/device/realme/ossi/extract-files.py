#!/usr/bin/env -S PYTHONPATH=../../../tools/extract-utils python3
#
# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#

import os
from pathlib import Path

from extract_utils.fixups_blob import (
    blob_fixup,
    blob_fixups_user_type,
)
from extract_utils.fixups_lib import (
    lib_fixup_remove,
    lib_fixups,
    lib_fixups_user_type,
)
from extract_utils.main import (
    ExtractUtils,
    ExtractUtilsModule,
)

platform_sdk = int(os.environ.get('OSSI_PLATFORM_SDK', '35'))
if platform_sdk not in (34, 35, 36):
    raise ValueError(f'Unsupported ossi platform SDK: {platform_sdk}')

namespace_imports = [
    'device/realme/ossi',
    'hardware/oplus',
    'hardware/qcom-caf/sm8550',
    'hardware/qcom-caf/wlan',
    'vendor/qcom/opensource/commonsys/display',
    'vendor/qcom/opensource/commonsys-intf/display',
    'vendor/qcom/opensource/dataservices',
]
if Path('../../../hardware/pixelworks/interfaces/Android.bp').is_file():
    namespace_imports.append('hardware/pixelworks/interfaces')


def lib_fixup_odm_suffix(lib: str, partition: str, *args, **kwargs):
    return f'{lib}_{partition}' if partition == 'odm' else None


def lib_fixup_vendor_suffix(lib: str, partition: str, *args, **kwargs):
    return f'{lib}_{partition}' if partition == 'vendor' else None


lib_fixups: lib_fixups_user_type = {
    **lib_fixups,
    (
        'libpwirisfeature',
        'libpwirishalwrapper',
    ): lib_fixup_odm_suffix,
    (
        'com.qualcomm.qti.dpm.api@1.0',
        'libQnnCpu',
        'libQnnHtp',
        'libQnnHtpPrepare',
        'libQnnHtpV73Stub',
        'libhwconfigurationutil',
        'vendor.oplus.hardware.camera_rfi-V1-ndk',
        'vendor.oplus.hardware.cammidasservice-V1-ndk',
        'vendor.oplus.hardware.communicationcenter-V2-ndk',
        'vendor.oplus.hardware.cwb@1.0',
        'vendor.oplus.hardware.olc2-V2-ndk',
        'vendor.oplus.hardware.sendextcamcmd-V2-ndk',
        'vendor.pixelworks.hardware.display@1.0',
        'vendor.pixelworks.hardware.display@1.1',
        'vendor.pixelworks.hardware.display@1.2',
        'vendor.pixelworks.hardware.feature@1.0',
        'vendor.pixelworks.hardware.feature@1.1',
        'vendor.qti.diaghal@1.0',
        'vendor.qti.hardware.dpmservice@1.0',
        'vendor.qti.hardware.qccsyshal@1.0',
        'vendor.qti.hardware.qccsyshal@1.1',
        'vendor.qti.hardware.qccsyshal@1.2',
        'vendor.qti.hardware.qccvndhal@1.0',
        'vendor.qti.hardware.wifidisplaysession@1.0',
        'vendor.qti.imsrtpservice@3.0',
        'vendor.qti.imsrtpservice@3.1',
    ): lib_fixup_vendor_suffix,
    (
        'libar-acdb',
        'libar-gsl',
        'liblx-osal',
        'libats',
        'libagmclient',
        'libpalclient',
        'vendor.qti.hardware.AGMIPC@1.0-impl',
    ): lib_fixup_remove,
}

blob_fixups: blob_fixups_user_type = {
    'odm/etc/camera/CameraHWConfiguration.config': blob_fixup()
        .regex_replace('SystemCamera =  0;  0;  1;  1;  1;', 'SystemCamera =  0;  0;  0;  0;  0;'),
    'odm/etc/libnfc-nci.conf': blob_fixup()
        .regex_replace('NFC_DEBUG_ENABLED=1', 'NFC_DEBUG_ENABLED=0'),
    'odm/etc/permissions/vendor-oplus-hardware-cryptoeng.xml': blob_fixup()
        .regex_replace(r'</permissions>\s*<permissions>', ''),
    'odm/lib64/libAlgoProcess.so': blob_fixup()
        .replace_needed('android.hardware.graphics.common-V3-ndk.so', 'android.hardware.graphics.common-V6-ndk.so'),
    (
        'odm/lib64/libCOppLceTonemapAPI.so',
        'odm/lib64/libCS.so',
        'odm/lib64/libSuperRaw.so',
        'odm/lib64/libYTCommon.so',
        'odm/lib64/libyuv2.so',
    ): blob_fixup()
        .replace_needed('libstdc++.so', 'libstdc++_vendor.so'),
    (
        'odm/lib64/libHIS.so',
        'odm/lib64/libOGLManager.so',
        'odm/lib64/libOPAlgoCamFaceBeautyCap.so',
    ): blob_fixup()
        .clear_symbol_version('AHardwareBuffer_allocate')
        .clear_symbol_version('AHardwareBuffer_describe')
        .clear_symbol_version('AHardwareBuffer_lock')
        .clear_symbol_version('AHardwareBuffer_release')
        .clear_symbol_version('AHardwareBuffer_unlock'),
    'odm/lib64/libarcsoft_high_dynamic_range_v4.so': blob_fixup()
        .clear_symbol_version('remote_handle_close')
        .clear_symbol_version('remote_handle_invoke')
        .clear_symbol_version('remote_handle_open')
        .clear_symbol_version('remote_register_buf_attr')
        .clear_symbol_version('remote_register_buf'),
    'odm/lib64/libextensionlayer.so': blob_fixup()
        .replace_needed('libziparchive.so', 'libziparchive_odm.so'),
    'product/etc/sysconfig/com.android.hotwordenrollment.common.util.xml': blob_fixup()
        .regex_replace('/my_product', '/product'),
    ('vendor/bin/hw/android.hardware.security.keymint-service-qti', 'vendor/lib64/libqtikeymint.so'): blob_fixup()
        .add_needed('android.hardware.security.rkp-V3-ndk.so'),
    ('vendor/etc/media_codecs_kalama.xml', 'vendor/etc/media_codecs_kalama_vendor.xml'): blob_fixup()
        .regex_replace('.*media_codecs_(google_audio|google_c2|google_telephony|google_video|vendor_audio).*\n', ''),
    'vendor/etc/seccomp_policy/qwesd@2.0.policy': blob_fixup()
        .add_line_if_missing('pipe2: 1'),
}  # fmt: skip

# The LineageOS compat libraries and Oplus fingerprint shim vary by release.
if platform_sdk == 34:
    blob_fixups.update({
        'system_ext/lib64/libwfdnative.so': blob_fixup()
            .replace_needed('android.hidl.base@1.0.so', 'libhidlbase.so'),
        'system_ext/lib64/libwfdservice.so': blob_fixup()
            .replace_needed('android.media.audio.common.types-V2-cpp.so',
                            'android.media.audio.common.types-V3-cpp.so'),
    })
else:
    fingerprint = blob_fixup()
    if platform_sdk == 36:
        fingerprint.replace_needed('libtinyxml2.so', 'libtinyxml2-v34.so')
    blob_fixups.update({
        'odm/bin/hw/vendor.oplus.hardware.biometrics.fingerprint@2.1-service_uff': fingerprint
            .add_needed('libshims_aidl_fingerprint_v2.oplus.so'),
        'odm/etc/init/init.network.rc': blob_fixup()
            .regex_replace(r'/\* (Huo\.Chen@SYSTEM\.RF, 2024/09/06, Add for ICC) \*/', r'# \1'),
        'vendor/lib64/libqcodec2_core.so': blob_fixup()
            .add_needed('libcodec2_shim.so'),
        'vendor/lib64/vendor.libdpmframework.so': blob_fixup()
            .add_needed('libhidlbase_shim.so'),
    })
if platform_sdk == 35:
    blob_fixups.update({
        'odm/bin/hw/vendor.oplus.hardware.biometrics.face@1.0-service': blob_fixup()
            .clear_symbol_version(
                '_ZN7android4base4TrimERKNSt3__112basic_stringIcNS1_11char_traitsIcEENS1_9allocatorIcEEEE'
            )
            .add_needed('libbase_shim.so'),
        'odm/bin/hw/vendor.oplus.hardware.charger-V5-service': blob_fixup()
            .add_needed('libbase_shim.so'),
        'system_ext/bin/wfdservice64': blob_fixup()
            .add_needed('libwfdservice_shim.so'),
        'system_ext/lib64/libwfdservice.so': blob_fixup()
            .replace_needed('android.media.audio.common.types-V2-cpp.so',
                            'android.media.audio.common.types-V4-cpp.so'),
        'system_ext/lib64/libwfdnative.so': blob_fixup()
            .replace_needed('android.hidl.base@1.0.so', 'libhidlbase.so'),
    })
if platform_sdk == 36:
    blob_fixups.update({
        'odm/bin/hw/vendor.oplus.hardware.charger-V11-service': blob_fixup()
            .add_needed('libbase_shim.so'),
        ('odm/bin/touchDaemon', 'vendor/lib64/libdpps.so',
         'vendor/lib64/libsnapdragoncolor-manager.so'): blob_fixup()
            .replace_needed('libtinyxml2.so', 'libtinyxml2-v34.so'),
        'system_ext/bin/horae': blob_fixup()
            .replace_needed('libprotobuf-cpp-lite.so', 'libprotobuf-cpp-lite-21.7.so'),
        'system_ext/lib64/libwfdnative.so': blob_fixup()
            .add_needed('libinput_shim.so'),
        'system_ext/lib64/vendor.qti.hardware.qccsyshal@1.2-halimpl.so': blob_fixup()
            .replace_needed('libprotobuf-cpp-full.so', 'libprotobuf-cpp-full-21.7.so'),
        'vendor/bin/hw/android.hardware.contexthub-service.qmi': blob_fixup()
            .replace_needed('libbase.so', 'libbase-v33.so'),
    })

module = ExtractUtilsModule(
    'ossi',
    'realme',
    blob_fixups=blob_fixups,
    lib_fixups=lib_fixups,
    namespace_imports=namespace_imports,
)

if __name__ == '__main__':
    utils = ExtractUtils.device(module)
    utils.run()
