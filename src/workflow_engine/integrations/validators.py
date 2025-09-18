"""
Schema验证器实现
"""
from typing import Dict, Any, List, Optional, Union
import json
import jsonschema
from jsonschema import Draft7Validator, ValidationError
from pydantic import BaseModel, ValidationError as PydanticValidationError
import logging


logger = logging.getLogger(__name__)


class SchemaValidator:
    """Schema验证器"""
    
    def __init__(self):
        self.validators_cache: Dict[str, Draft7Validator] = {}
    
    def validate(
        self, 
        data: Dict[str, Any], 
        schema: Union[Dict[str, Any], BaseModel]
    ) -> List[str]:
        """
        验证数据是否符合schema定义
        
        Args:
            data: 待验证的数据
            schema: JSON Schema定义或Pydantic模型
            
        Returns:
            验证错误列表，如果没有错误返回空列表
        """
        errors = []
        
        try:
            if isinstance(schema, type) and issubclass(schema, BaseModel):
                # Pydantic模型验证
                errors = self._validate_with_pydantic(data, schema)
            elif isinstance(schema, dict):
                # JSON Schema验证
                errors = self._validate_with_jsonschema(data, schema)
            elif hasattr(schema, 'dict'):
                # Pydantic实例转为dict处理
                errors = self._validate_with_jsonschema(data, schema.dict())
            else:
                errors.append(f"Unsupported schema type: {type(schema)}")
        
        except Exception as e:
            logger.error(f"Schema validation error: {str(e)}", exc_info=True)
            errors.append(f"Validation failed: {str(e)}")
        
        return errors
    
    def _validate_with_pydantic(
        self, 
        data: Dict[str, Any], 
        model_class: type[BaseModel]
    ) -> List[str]:
        """使用Pydantic模型验证"""
        errors = []
        
        try:
            # 尝试创建模型实例
            model_class(**data)
        except PydanticValidationError as e:
            # 提取所有验证错误
            for error in e.errors():
                field_path = ".".join(str(loc) for loc in error["loc"])
                message = error["msg"]
                errors.append(f"{field_path}: {message}")
        
        return errors
    
    def _validate_with_jsonschema(
        self, 
        data: Dict[str, Any], 
        schema: Dict[str, Any]
    ) -> List[str]:
        """使用JSON Schema验证"""
        errors = []
        
        # 获取或创建验证器
        schema_str = json.dumps(schema, sort_keys=True)
        if schema_str not in self.validators_cache:
            try:
                self.validators_cache[schema_str] = Draft7Validator(schema)
            except Exception as e:
                errors.append(f"Invalid schema: {str(e)}")
                return errors
        
        validator = self.validators_cache[schema_str]
        
        # 收集所有验证错误
        for error in validator.iter_errors(data):
            path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
            errors.append(f"{path}: {error.message}")
        
        return errors
    
    def validate_partial(
        self, 
        data: Dict[str, Any], 
        schema: Dict[str, Any],
        required_fields: Optional[List[str]] = None
    ) -> List[str]:
        """
        部分验证 - 只验证提供的字段
        
        Args:
            data: 待验证的数据
            schema: JSON Schema定义
            required_fields: 必需字段列表（覆盖schema中的required）
            
        Returns:
            验证错误列表
        """
        # 创建schema副本
        partial_schema = schema.copy()
        
        # 调整必需字段
        if required_fields is not None:
            partial_schema["required"] = required_fields
        else:
            # 移除所有必需字段要求
            partial_schema.pop("required", None)
        
        return self._validate_with_jsonschema(data, partial_schema)
    
    def merge_schemas(
        self, 
        base_schema: Dict[str, Any], 
        override_schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        合并两个schema定义
        
        Args:
            base_schema: 基础schema
            override_schema: 覆盖schema
            
        Returns:
            合并后的schema
        """
        merged = base_schema.copy()
        
        # 合并properties
        if "properties" in override_schema:
            merged.setdefault("properties", {})
            merged["properties"].update(override_schema["properties"])
        
        # 合并required
        if "required" in override_schema:
            base_required = set(merged.get("required", []))
            override_required = set(override_schema["required"])
            merged["required"] = list(base_required | override_required)
        
        # 覆盖其他顶层属性
        for key, value in override_schema.items():
            if key not in ["properties", "required"]:
                merged[key] = value
        
        return merged
    
    def generate_example(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据schema生成示例数据
        
        Args:
            schema: JSON Schema定义
            
        Returns:
            示例数据
        """
        example = {}
        
        if "properties" not in schema:
            return example
        
        for prop_name, prop_schema in schema["properties"].items():
            example[prop_name] = self._generate_value_for_type(prop_schema)
        
        return example
    
    def _generate_value_for_type(self, prop_schema: Dict[str, Any]) -> Any:
        """根据类型生成示例值"""
        prop_type = prop_schema.get("type", "string")
        
        if "example" in prop_schema:
            return prop_schema["example"]
        elif "default" in prop_schema:
            return prop_schema["default"]
        elif "enum" in prop_schema:
            return prop_schema["enum"][0]
        
        # 根据类型生成默认值
        type_defaults = {
            "string": "example_string",
            "number": 0.0,
            "integer": 0,
            "boolean": True,
            "array": [],
            "object": {},
            "null": None
        }
        
        return type_defaults.get(prop_type, None)
    
    def format_validation_errors(
        self, 
        errors: List[str], 
        max_errors: Optional[int] = None
    ) -> str:
        """
        格式化验证错误为可读字符串
        
        Args:
            errors: 错误列表
            max_errors: 最多显示的错误数量
            
        Returns:
            格式化的错误信息
        """
        if not errors:
            return "No validation errors"
        
        if max_errors and len(errors) > max_errors:
            displayed_errors = errors[:max_errors]
            remaining = len(errors) - max_errors
            formatted_errors = "\n".join(f"  - {error}" for error in displayed_errors)
            return f"Validation errors:\n{formatted_errors}\n  ... and {remaining} more errors"
        else:
            formatted_errors = "\n".join(f"  - {error}" for error in errors)
            return f"Validation errors:\n{formatted_errors}"
