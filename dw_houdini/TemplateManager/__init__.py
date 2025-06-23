"""
GLOBALS for the manager
"""

# hardcoded project path and json names
template_path = "C:\\template_path\\hou_template"
template_json_path = template_path + "\\template_data.json"
template_json_archive_name = "template_data_archive.json"

# default format for empty jsons, i guess we could use only the second one for both
new_template_json = {
    "file_counter": 0,
    "version": 0,
    "houdini_cfx_templates": {
        "cfx_template": {
            "files": []
        }
    }
}

new_archived_template_json = {
    "file_counter": 0,
    "version": 0,
    "archived_cfx_categories": {},
    "houdini_cfx_templates": {
        "cfx_template": {
            "files": []
        }
    }
}