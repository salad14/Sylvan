"""ROS 自定义消息环境装载（原 setup_env.py 的纯搬运）。"""

from __future__ import annotations

import os
import subprocess
import sys
import traceback

from ..config.logging_config import get_logger


def setup_ros_environment(workspace: str | None = None) -> bool:
    """设置 ROS 环境变量与 Python 路径；返回是否能导入 Gongjicarla。

    参数 workspace：默认 ``~/carlatest_ws``。
    """
    logger = get_logger()
    try:
        logger.info("设置ROS环境...")

        user_workspace = workspace or os.path.expanduser("~/carlatest_ws")
        if not os.path.exists(user_workspace):
            logger.warning(f"找不到ROS工作空间: {user_workspace}")
            logger.warning("自定义消息类型可能无法正常工作")
            return False

        install_lib_path = os.path.join(
            user_workspace,
            "install",
            "testcarla_interfaces",
            "lib",
            "python3.10",
            "site-packages",
        )
        if os.path.exists(install_lib_path):
            logger.info(f"添加路径到PYTHONPATH: {install_lib_path}")
            if install_lib_path not in sys.path:
                sys.path.insert(0, install_lib_path)
        else:
            logger.warning(f"找不到ROS消息库路径: {install_lib_path}")

            python_dirs: list[str] = []
            install_root = os.path.join(user_workspace, "install")
            if os.path.exists(install_root):
                for root, dirs, _files in os.walk(install_root):
                    python_dirs.extend(
                        [os.path.join(root, d) for d in dirs if d.startswith("python")]
                    )
            if python_dirs:
                logger.info(f"找到可能的Python路径: {python_dirs}")
                for path in python_dirs:
                    if path not in sys.path:
                        sys.path.insert(0, path)

            try:
                result = subprocess.check_output(
                    [
                        "bash",
                        "-c",
                        "source ~/carlatest_ws/install/setup.bash && "
                        "python3 -c 'import sys; print(\"\\n\".join(sys.path))'",
                    ],
                    universal_newlines=True,
                )
                for path in result.strip().split("\n"):
                    if "testcarla_interfaces" in path and path not in sys.path:
                        logger.info(f"从ROS环境添加路径: {path}")
                        sys.path.insert(0, path)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"获取ROS路径失败: {e}")

        os.environ["PYTHONPATH"] = ":".join(sys.path)

        try:
            from testcarla_interfaces.msg import Gongjicarla  # type: ignore  # noqa: F401

            logger.info("成功导入Gongjicarla消息类型！")
            return True
        except ImportError as e:
            logger.warning(f"导入自定义消息失败: {e}")
            return False
    except Exception as e:  # noqa: BLE001
        logger.error(f"设置ROS环境失败: {e}")
        logger.error(traceback.format_exc())
        return False
