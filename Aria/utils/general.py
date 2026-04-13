import unicodedata


def format_message(message): return f"**[AFK]** {message}"
def quote_block(text): return "\n".join([f"> {line}" for line in text.split("\n")])


def is_valid_emoji(char):
	if not char:
		return False
	value = str(char)
	if len(value) > 2 and value.startswith("<") and value.endswith(">"):
		return True
	for symbol in value:
		category = unicodedata.category(symbol)
		if category == "So" or "EMOJI" in unicodedata.name(symbol, ""):
			return True
	return False
