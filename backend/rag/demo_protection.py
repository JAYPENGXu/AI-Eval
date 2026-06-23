from django.conf import settings
from rest_framework.exceptions import PermissionDenied


DEMO_DOCUMENTS = {
    "ragpilot_demo_guide.pdf",
    "xinghai_employee_handbook.pdf",
    "xinghai_engineering_release.pdf",
    "xinghai_compensation_policy.pdf",
    "xinghai_personal_salary_linxiao.pdf",
    "xinghai_mixed_ocr_dr.pdf",
    "yuanhang_vendor_delivery.pdf",
}
DEMO_POLICIES = {
    "全员内部资料", "研发机密资料", "HR 薪酬受限资料", "林晓个人薪资", "供应商内部资料",
}


def demo_protected(organization) -> bool:
    return bool(settings.DEMO_MODE and organization and organization.is_demo)


def deny_demo_core_mutation(organization, message="公共演示环境的预置数据受保护，定时重置由服务端执行。"):
    if demo_protected(organization):
        raise PermissionDenied(message)


def deny_seed_document_mutation(document, message="预置演示文档不可修改；可以上传并操作自己的临时文档。"):
    if demo_protected(document.kb.organization) and document.filename in DEMO_DOCUMENTS:
        raise PermissionDenied(message)


def deny_seed_document_delete(document):
    deny_seed_document_mutation(document, "预置演示文档不可删除；可以上传并操作自己的临时文档。")
