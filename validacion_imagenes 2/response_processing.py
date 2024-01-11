import re
import json

def remove_markdown_format(text:str)->str:
    """Remove markdown format from a string

    Args:
        text (str): string to remove markdown format

    Returns:
        str: string without markdown format
    """
    text = re.sub(r'\*\*([^\*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^\*]+)\*', r'\1', text)
    text = re.sub(r'\_([^\_]+)\_', r'\1', text)
    text = re.sub(r'\~([^\~]+)\~', r'\1', text)
    text = re.sub(r'\`([^\`]+)\`', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'\!\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'\n', r' ', text)
    text = re.sub(r'\s+', r' ', text)
    return text.strip()


def parse_json(text:str)->dict:
    """Parse a string to a json object

    Args:
        text (str): string to parse

    Returns:
        dict: json object
    """
    try:
        return json.loads(text)
    except:
        clean_text = remove_markdown_format(text)
        clean_text = clean_text.replace("'", '"')\
                                .replace("True", "true")\
                                .replace("False", "false")\
                                .replace("`", "")\
                                .replace("json", "")\
                                .replace("JSON", "")\
                                .replace("Json", "")
        try:
            return json.loads(clean_text)
        except:
            return {}
                            
    