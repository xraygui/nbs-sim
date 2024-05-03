
import toml


def apply_default_values(data):
    """
    Goes through the groups in data, finds the _default values, and applies them to all the other items in each group.
    Creates a new dictionary without modifying the original one and does not include the _default key in the new dictionary.

    Parameters:
    data (dict): The nested dictionary containing groups with potential "_default" keys.

    Returns:
    dict: The new dictionary with _default values applied to each group, excluding the _default key itself.
    """
    new_data = {}
    for group_key, group_value in data.items():
        if isinstance(group_value, dict):
            # Initialize a new group excluding the _default key
            new_group = {k: v for k, v in group_value.items() if k != "_default"}
            default_values = group_value.get("_default", {})
            for item_key, item_value in new_group.items():
                if isinstance(item_value, dict):
                    # Apply default values to the item, update only if the key is not present
                    for default_key, default_val in default_values.items():
                        item_value.setdefault(default_key, default_val)
            new_data[group_key] = new_group
        else:
            # Copy the value as is if it's not a dictionary
            new_data[group_key] = group_value
    return new_data


def replace_target_values(data, translation_dict, default_target=None, last_key=None):
    """
    Recursively replaces target values in a nested dictionary based on a translation dictionary.

    Parameters:
    data (dict): The nested dictionary whose values are to be replaced.
    translation_dict (dict): A dictionary mapping class names to their new values. Used to replace "_target_" values in the data.
    default_target (str, optional): A default translation for class names that are not provided in translation_dict. If None, classes not found in the translation_dict will raise a KeyError.
    last_key (str, optional): The last key accessed in the recursive call, used for specific translations like prefix handling.

    Returns:
    dict: The modified dictionary with replaced values.
    """
    new_data = {}
    for key, value in data.items():
        if key == "_target":
            class_name = value.split(".")[-1]
            if value in translation_dict:
                new_data[key] = translation_dict[value]
            elif class_name in translation_dict:
                new_data[key] = translation_dict[class_name]
            elif default_target is not None:
                new_data[key] = default_target
            else:
                print(
                    f"Warning: {class_name} not found in translation_dict and no default target was provided."
                )
                return {}
        #elif key == "long_name":
        #    new_data["label"] = data["long_name"]
        elif key == "prefix":
            new_data["prefix"] = data['prefix']
        elif key == "_group":
            new_data["_group"] = data["_group"]
        elif isinstance(value, dict):
            replaced_value = replace_target_values(
                value, translation_dict, default_target, key
            )
            if replaced_value:
                new_data[key] = replaced_value
    return new_data


def group_keys(data):
    new_data = {}
    for key, value in data.items():
        group = value.pop("_group", "misc")
        if group not in new_data:
            new_data[group] = {}
        new_data[group][key] = value
    return new_data


def convert_config(config_dict, translation_updates={}, default_target=None):
    """
    Converts a beamline config file into a GUI config file using a default class mapping.

    Parameters:
    input_filename (str): The path to the input YAML file to be modified.
    output_filename (str): The path where the modified YAML data will be written.
    translation_dict (dict): A dictionary mapping class names to their new values.

    Returns:
    None
    """
    default_translation_dict = {"EpicsMotor": "caproto.ioc_examples.fake_motor_record"}
    default_translation_dict.update(translation_updates)
    new_config = replace_target_values(
        config_dict, default_translation_dict, default_target
    )
    new_config = group_keys(new_config)
    return new_config


def load_device_config(
    device_file, gui_file=None, translation_updates={}, default_target=None
):
    with open(device_file, "r") as f:
        device_config = toml.load(f)
    if gui_file is not None:
        with open(gui_file, "r") as f:
            gui_config = toml.load(f)
    else:
        gui_config = {}
    translation_updates.update(gui_config.get("loaders", {}))
    new_dev_config = convert_config(device_config, translation_updates, default_target)
    update_devices = gui_config.get("devices", {})
    for key in list(new_dev_config.keys()):
        update_section = update_devices.get(key, {})
        if update_section.get("exclude", False):
            new_dev_config.pop(key)
        else:
            section = new_dev_config[key]
            for dkey in list(section.keys()):
                if update_section.get(dkey, {}).get("exclude", False):
                    section.pop(dkey, None)
                    continue
                else:
                    section[dkey].update(update_section.get(dkey, {}))
    return new_dev_config
