Map<String, dynamic> mapValue(Object? value) {
  return value is Map<String, dynamic> ? value : const {};
}

List<dynamic> listValue(Object? value) {
  return value is List<dynamic> ? value : const [];
}

String textValue(Object? value) {
  if (value == null || value == '') return '-';
  return value.toString();
}
