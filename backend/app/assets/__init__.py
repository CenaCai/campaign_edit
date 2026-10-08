"""资产层：静态图片的上传、引用分析、导出集成。

分层：
  storage.py  可插拔存储适配器（Local 零依赖 / S3 延迟导入）
  service.py  入库去重、schema 引用扫描、导出时内联或打包
"""
__all__ = ["storage", "service"]