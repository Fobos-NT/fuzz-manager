import java.io.ByteArrayInputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

import de.siegmar.fastcsv.reader.CsvReader;
import de.siegmar.fastcsv.reader.CsvParseException;

public class CsvReaderFuzzer {
  public static void fuzzerTestOneInput(byte[] input) {
    try {
      CsvReader.builder()
        .ofCsvRecord(new InputStreamReader(new ByteArrayInputStream(input), StandardCharsets.UTF_8))
        .stream()
        .toList();
    } catch (CsvParseException e) {
    }
  }
}