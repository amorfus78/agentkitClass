export const groupBy = (array: any[], key: string, defaultGroup: string = "default") => {
  const grouped = new Map<string, any[]>();

  array.forEach(currentValue => {
    const result_key = currentValue?.[key] ?? defaultGroup;
    if (!grouped.has(result_key)) {
      grouped.set(result_key, []);
    }
    grouped.get(result_key)!.push(currentValue);
  });

  return grouped;
}
