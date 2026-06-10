"""分层渲染（建筑/植被/围栏/杆状物/墙壁/护栏）。

"""

from __future__ import annotations

import traceback
from typing import Iterable

import carla

from ..config.constants import RENDER_LAYERS, WINDOW_HEIGHT, WINDOW_WIDTH
from ..config.logging_config import get_logger

_logger = get_logger()


class LayeredRenderer:
    """按类型动态隐藏/恢复 CARLA 世界中的环境对象。"""

    def __init__(self, world: carla.World, client: carla.Client):
        self.world = world
        self.client = client
        self.render_layers: dict[str, bool] = RENDER_LAYERS.copy()
        self.hidden_objects_by_type: dict[str, list[int]] = {}
        self.semantic_camera: carla.Actor | None = None
        self.layered_surface = None

    def debug_city_object_labels(self) -> None:
        try:
            _logger.info("=== 调试CARLA CityObjectLabel属性 ===")
            attrs = [a for a in dir(carla.CityObjectLabel) if not a.startswith("_")]
            _logger.info(f"找到 {len(attrs)} 个CityObjectLabel属性:")
            for attr in sorted(attrs):
                try:
                    _logger.info(f"  {attr}: {getattr(carla.CityObjectLabel, attr)}")
                except Exception as e:  # noqa: BLE001
                    _logger.warning(f"  {attr}: Error - {e}")
        except Exception as e:  # noqa: BLE001
            _logger.error(f"调试CityObjectLabel失败: {e}")

    def setup_semantic_camera(self, vehicle: carla.Actor) -> carla.Actor | None:
        try:
            _logger.info("设置语义分割相机...")
            blueprint_library = self.world.get_blueprint_library()
            bp = blueprint_library.find("sensor.camera.semantic_segmentation")
            bp.set_attribute("image_size_x", str(WINDOW_WIDTH // 4))
            bp.set_attribute("image_size_y", str(WINDOW_HEIGHT // 4))
            bp.set_attribute("fov", "90")

            transform = carla.Transform(
                carla.Location(x=1.5, y=0.0, z=2.0),
                carla.Rotation(pitch=0),
            )
            self.semantic_camera = self.world.spawn_actor(
                bp, transform, attach_to=vehicle, attachment_type=carla.AttachmentType.Rigid
            )
            _logger.info("语义分割相机已创建")
            return self.semantic_camera
        except Exception as e:  # noqa: BLE001
            _logger.error(f"创建语义分割相机失败: {e}")
            return None

    def toggle_layer(self, layer_name: str) -> bool:
        if layer_name in self.render_layers:
            self.render_layers[layer_name] = not self.render_layers[layer_name]
            _logger.info(
                f"渲染层 {layer_name}: {'开启' if self.render_layers[layer_name] else '关闭'}"
            )
            self._apply_layer_settings()
            return True
        return False

    def set_layer(self, layer_name: str, enabled: bool) -> bool:
        if layer_name in self.render_layers:
            self.render_layers[layer_name] = enabled
            _logger.info(f"渲染层 {layer_name}: {'开启' if enabled else '关闭'}")
            self._apply_layer_settings()
            return True
        return False

    def remove_environment_objects(self, object_types: Iterable[str]) -> bool:
        removed_count = 0
        try:
            carla_labels: dict[str, int] = {}
            label_attempts = [
                ("BUILDINGS", ["Buildings"]),
                ("VEGETATION", ["Vegetation"]),
                ("FENCES", ["Fences"]),
                ("POLES", ["Poles"]),
                ("WALLS", ["Walls"]),
                ("GUARDRAILS", ["GuardRails", "Guardrails", "GUARDRAILS"]),
            ]
            for obj_type, names in label_attempts:
                for name in names:
                    try:
                        if hasattr(carla.CityObjectLabel, name):
                            carla_labels[obj_type] = getattr(carla.CityObjectLabel, name)
                            _logger.debug(f"成功添加标签 {obj_type} -> {name}")
                            break
                    except AttributeError:
                        continue
                else:
                    _logger.warning(
                        f"CARLA中没有找到 {obj_type} 相关标签（尝试了: {names}）"
                    )

            _logger.info(f"成功加载的环境对象标签: {list(carla_labels.keys())}")
            if not carla_labels:
                _logger.error("没有找到任何可用的环境对象标签！")
                if hasattr(carla, "CityObjectLabel"):
                    attrs = [a for a in dir(carla.CityObjectLabel) if not a.startswith("_")]
                    _logger.info(f"CityObjectLabel所有可用属性: {attrs}")
                else:
                    _logger.error("CityObjectLabel类不存在！")

            for obj_type in object_types:
                if obj_type not in carla_labels:
                    _logger.warning(f"未知的对象类型: {obj_type}")
                    continue
                try:
                    _logger.info(f"开始移除 {obj_type}...")
                    try:
                        env_objects = self.world.get_environment_objects(carla_labels[obj_type])
                        _logger.info(f"找到 {len(env_objects)} 个 {obj_type} 对象")
                        if env_objects:
                            object_ids = [obj.id for obj in env_objects]
                            _logger.debug(f"{obj_type} 对象ID列表: {object_ids[:10]}...")
                            try:
                                self.world.enable_environment_objects(object_ids, False)
                                _logger.info(f"已成功隐藏 {len(object_ids)} 个 {obj_type}")
                                self.world.tick()
                                self.hidden_objects_by_type[obj_type] = object_ids
                                removed_count += len(object_ids)
                            except Exception as hide_error:  # noqa: BLE001
                                _logger.error(f"隐藏 {obj_type} 对象时失败: {hide_error}")
                        else:
                            _logger.warning(f"地图中没有找到 {obj_type} 类型的对象")
                    except Exception as get_error:  # noqa: BLE001
                        _logger.error(f"获取 {obj_type} 对象时失败: {get_error}")
                except Exception as e:  # noqa: BLE001
                    _logger.error(f"处理 {obj_type} 时发生未知错误: {e}")
                    _logger.error(f"错误详情: {traceback.format_exc()}")
                    continue
            return removed_count > 0
        except Exception as e:  # noqa: BLE001
            _logger.error(f"移除环境对象失败: {e}")
            _logger.error(traceback.format_exc())
            return False

    def restore_environment_objects(self, object_types: Iterable[str]) -> bool:
        restored_count = 0
        try:
            for obj_type in object_types:
                if obj_type in self.hidden_objects_by_type:
                    object_ids = self.hidden_objects_by_type[obj_type]
                    _logger.info(f"恢复 {obj_type} 显示...")
                    self.world.enable_environment_objects(object_ids, True)
                    _logger.info(f"已恢复 {len(object_ids)} 个 {obj_type}")
                    del self.hidden_objects_by_type[obj_type]
                    restored_count += len(object_ids)
            return restored_count > 0
        except Exception as e:  # noqa: BLE001
            _logger.error(f"恢复环境对象失败: {e}")
            return False

    # 向后兼容 -------------------------------------------------------------
    def remove_buildings(self) -> bool:
        return self.remove_environment_objects(["BUILDINGS"])

    def restore_buildings(self) -> bool:
        return self.restore_environment_objects(["BUILDINGS"])

    def remove_clean_environment(self) -> bool:
        _logger.info("开始创造干净的环境：移除建筑物、植被和围栏...")
        targets = ["BUILDINGS", "VEGETATION", "FENCES", "POLES", "WALLS"]
        success = self.remove_environment_objects(targets)
        if not success:
            _logger.info("标准方法失败，尝试使用替代方法移除环境对象...")
            return self._remove_environment_alternative_method()
        return success

    def _remove_environment_alternative_method(self) -> bool:
        try:
            _logger.info("尝试使用替代方法移除环境对象...")
            try:
                all_actors = self.world.get_actors()
                static_actors = all_actors.filter("static.*")
                _logger.info(f"找到 {len(static_actors)} 个静态对象")
                if len(static_actors) > 0:
                    for actor in static_actors:
                        try:
                            actor.set_simulate_physics(False)
                        except Exception:  # noqa: BLE001
                            pass
                    _logger.info("已尝试处理静态对象")
                    return True
            except Exception as e:  # noqa: BLE001
                _logger.error(f"处理静态对象失败: {e}")

            try:
                _ = self.world.get_settings()
                _logger.info("尝试修改世界设置...")
            except Exception as e:  # noqa: BLE001
                _logger.error(f"修改世界设置失败: {e}")
            return False
        except Exception as e:  # noqa: BLE001
            _logger.error(f"替代方法失败: {e}")
            return False

    def restore_clean_environment(self) -> bool:
        _logger.info("恢复所有环境对象...")
        return self.restore_environment_objects(
            ["BUILDINGS", "VEGETATION", "FENCES", "POLES", "WALLS"]
        )

    def _apply_layer_settings(self) -> None:
        try:
            env_object_types = ["BUILDINGS", "VEGETATION", "FENCES", "POLES", "WALLS"]
            for obj_type in env_object_types:
                if obj_type in self.render_layers:
                    if not self.render_layers[obj_type]:
                        self.remove_environment_objects([obj_type])
                    else:
                        self.restore_environment_objects([obj_type])
            _logger.debug("分层渲染设置已应用")
        except Exception as e:  # noqa: BLE001
            _logger.error(f"应用分层渲染设置失败: {e}")

    def get_layer_status(self) -> dict[str, bool]:
        return self.render_layers.copy()

    def cleanup(self) -> None:
        if self.semantic_camera:
            try:
                self.semantic_camera.destroy()
                _logger.info("语义分割相机已销毁")
            except Exception:  # noqa: BLE001
                pass
        try:
            if hasattr(self, "hidden_objects_by_type"):
                for obj_type in list(self.hidden_objects_by_type.keys()):
                    self.restore_environment_objects([obj_type])
        except Exception as e:  # noqa: BLE001
            _logger.error(f"恢复隐藏对象时出错: {e}")
        _logger.info("分层渲染器资源已清理")
