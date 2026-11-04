package quickstart;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.function.Consumer;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.stream.Stream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import software.amazon.awssdk.core.SdkBytes;
import software.amazon.awssdk.core.document.Document;
import software.amazon.awssdk.services.devopsagent.DevOpsAgentClient;
import software.amazon.awssdk.services.devopsagent.model.Asset;
import software.amazon.awssdk.services.devopsagent.model.AssetContent;
import software.amazon.awssdk.services.devopsagent.model.DevOpsAgentException;
import software.amazon.awssdk.services.devopsagent.model.ListAssetsResponse;

/** Install the official skills in skills/ into an Agent Space. */
public final class Skills {
  public static final String GITHUB_TREE =
      "https://github.com/aws/tools-for-devops-agent/tree/main/skills/";
  public static final List<String> RUNTIME_PARTS = List.of("SKILL.md", "references", "assets");
  public static final int MAX_ZIP = 6 * 1024 * 1024;
  public static final Set<String> AGENT_TYPES = Set.of("GENERIC", "CHAT", "INCIDENT_TRIAGE",
      "INCIDENT_RCA", "INCIDENT_MITIGATION", "INCIDENT_UI", "PREVENTION",
      "RELEASE_READINESS_REVIEW", "RELEASE_TESTING");
  /** --all skips these unless asked. You can still install them by name. */
  public static final Set<String> EXAMPLES = Set.of(
      "crm-production-investigation-guidelines", // demo CRM triage rules; turns off incident linking
      "skip-scheduled-maintenance"); // fixed sample window 2025-03-15
  public static final List<String> THIRD_PARTY_PREFIXES =
      List.of("honeycomb-", "grafana-", "sumo-logic-", "wiz-");

  private static final Pattern FRONTMATTER = Pattern.compile("\\A---\\n(.*?)\\n---", Pattern.DOTALL);
  private static final Pattern NAME = Pattern.compile("^name:\\s*['\"]?([\\w-]+)", Pattern.MULTILINE);
  private static final Pattern TYPES =
      Pattern.compile("aws-devops-agent-skills\\.agent-types:\\s*['\"]?([^'\"\\n]+)");

  private final Path skillsDir;

  public Skills(Path skillsDir) {
    this.skillsDir = skillsDir;
  }

  /**
   * Finds the repo's skills/ folder: $SKILLS_DIR, else walk up from the current directory,
   * else walk up from where the jar is.
   */
  public static Skills locate() {
    String env = System.getenv("SKILLS_DIR");
    if (env != null && !env.isEmpty()) return new Skills(Paths.get(env));
    List<Path> starts = new ArrayList<>();
    starts.add(Paths.get("").toAbsolutePath());
    try {
      starts.add(Paths.get(Skills.class.getProtectionDomain().getCodeSource().getLocation().toURI()));
    } catch (Exception ignored) {
      // no code source (e.g. some test runners)
    }
    for (Path start : starts) {
      for (Path p = start; p != null; p = p.getParent()) {
        Path d = p.resolve("skills");
        if (Files.isRegularFile(d.resolve("aws-health-events").resolve("SKILL.md"))) return new Skills(d);
      }
    }
    throw new IllegalStateException("skills/ folder not found; set SKILLS_DIR to the repo's skills folder");
  }

  /** java/dist next to the skills copy, the same place for every working directory. */
  public Path distDir() {
    return skillsDir.toAbsolutePath().getParent().resolve("java").resolve("dist");
  }

  public static boolean isThirdParty(String s) {
    return THIRD_PARTY_PREFIXES.stream().anyMatch(s::startsWith);
  }

  public static String tag(String s) {
    return EXAMPLES.contains(s) ? " (example)" : isThirdParty(s) ? " (third-party)" : "";
  }

  public List<String> all() {
    try (Stream<Path> s = Files.list(skillsDir)) {
      return s.filter(p -> Files.isRegularFile(p.resolve("SKILL.md")))
          .map(p -> p.getFileName().toString()).sorted().collect(Collectors.toList());
    } catch (IOException e) {
      throw new UncheckedIOException(e);
    }
  }

  public record Frontmatter(String name, List<String> agentTypes) {}

  public Frontmatter frontmatter(String skill) {
    String text;
    try {
      text = Files.readString(skillsDir.resolve(skill).resolve("SKILL.md"));
    } catch (IOException e) {
      throw new UncheckedIOException(e);
    }
    Matcher fm = FRONTMATTER.matcher(text);
    if (!fm.find()) throw new IllegalArgumentException(skill + ": SKILL.md has no frontmatter");
    Matcher n = NAME.matcher(fm.group(1));
    if (!n.find()) throw new IllegalArgumentException(skill + ": no name in frontmatter");
    Matcher t = TYPES.matcher(fm.group(1));
    List<String> types = t.find()
        ? Arrays.stream(t.group(1).split(",")).map(String::trim).collect(Collectors.toList())
        : List.of("GENERIC");
    for (String type : types) {
      if (!AGENT_TYPES.contains(type)) throw new IllegalArgumentException(skill + ": unknown agent type " + type);
    }
    return new Frontmatter(n.group(1), types);
  }

  /** Zip only SKILL.md, references/ and assets/, with SKILL.md at the zip root. */
  public byte[] buildZip(String skill) {
    if (!all().contains(skill)) throw new IllegalArgumentException("unknown skill: " + skill);
    Path src = skillsDir.resolve(skill);
    ByteArrayOutputStream buf = new ByteArrayOutputStream();
    try (ZipOutputStream z = new ZipOutputStream(buf)) {
      for (String part : RUNTIME_PARTS) {
        Path p = src.resolve(part);
        if (!Files.exists(p)) continue;
        List<Path> files;
        try (Stream<Path> w = Files.walk(p)) {
          files = w.filter(Files::isRegularFile).sorted().collect(Collectors.toList());
        }
        for (Path f : files) {
          z.putNextEntry(new ZipEntry(src.relativize(f).toString().replace('\\', '/')));
          z.write(Files.readAllBytes(f));
          z.closeEntry();
        }
      }
    } catch (IOException e) {
      throw new UncheckedIOException(e);
    }
    byte[] data = buf.toByteArray();
    if (data.length > MAX_ZIP) throw new IllegalStateException(skill + ": zip over the 6 MB limit");
    return data;
  }

  public List<String> defaults(boolean includeExamples, boolean includeThirdParty) {
    return all().stream()
        .filter(s -> includeExamples || !EXAMPLES.contains(s))
        .filter(s -> includeThirdParty || !isThirdParty(s))
        .collect(Collectors.toList());
  }

  public static Map<String, String> installedNames(DevOpsAgentClient client, String space) {
    Map<String, String> names = new TreeMap<>();
    String token = null;
    do {
      final String t = token;
      ListAssetsResponse page = client.listAssets(r -> r.agentSpaceId(space).assetType("skill")
          .maxResults(50).nextToken(t));
      for (Asset a : page.items()) {
        Document name = a.metadata() != null && a.metadata().isMap() ? a.metadata().asMap().get("name") : null;
        if (name != null && name.isString()) names.put(name.asString(), a.assetId());
      }
      token = page.nextToken();
    } while (token != null);
    return names;
  }

  /** Install skills; returns skill -> assetId, "skipped" or "failed". */
  public Map<String, String> install(DevOpsAgentClient client, String space, List<String> skills,
      boolean fromGithub, Consumer<String> log) {
    Map<String, String> have = installedNames(client, space);
    Map<String, String> results = new LinkedHashMap<>();
    for (String s : skills) {
      Frontmatter fm = frontmatter(s);
      if (have.containsKey(fm.name())) {
        log.accept("skip    " + s + " (already installed: " + have.get(fm.name()) + ")");
        results.put(s, "skipped");
        continue;
      }
      AssetContent content = fromGithub
          ? AssetContent.fromSourceUrl(u -> u.url(GITHUB_TREE + s))
          : AssetContent.fromZip(z -> z.zipFile(SdkBytes.fromByteArray(buildZip(s))));
      List<Document> types = new ArrayList<>();
      fm.agentTypes().forEach(t -> types.add(Document.fromString(t)));
      Document metadata = Document.fromMap(Map.of("agent_types", Document.fromList(types)));
      try {
        Asset asset = client.createAsset(r -> r.agentSpaceId(space).assetType("skill")
            .metadata(metadata).content(content)).asset();
        log.accept("install " + s + " -> " + asset.assetId() + " " + String.join(",", fm.agentTypes()));
        results.put(s, asset.assetId());
      } catch (DevOpsAgentException e) { // e.g. --from-github without a GitHub association
        log.accept("FAILED  " + s + ": " + e.awsErrorDetails().errorCode() + ": "
            + e.awsErrorDetails().errorMessage());
        results.put(s, "failed");
      }
    }
    return results;
  }
}
