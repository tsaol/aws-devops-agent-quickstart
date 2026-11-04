package quickstart;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.devopsagent.DevOpsAgentAsyncClient;
import software.amazon.awssdk.services.devopsagent.DevOpsAgentClient;

/**
 * AWS DevOps Agent quick start (Java).
 *
 * <pre>
 *   java -jar target/quickstart.jar ask "Which alarms fired in the last 24 hours?"
 *   java -jar target/quickstart.jar investigate "5xx spike on checkout API" "Started 14:05 UTC"
 *   java -jar target/quickstart.jar skills list | zip [skill...] | installed
 *   java -jar target/quickstart.jar skills install aws-routing [--from-github]
 *   java -jar target/quickstart.jar skills install --all [--include-examples] [--include-third-party]
 * </pre>
 *
 * Env: AGENT_SPACE_ID (not needed for skills list / zip); AWS_REGION, else AWS_DEFAULT_REGION, else
 * us-east-1; MAX_WAIT_MINUTES (default 60); SKILLS_DIR if the jar is used outside this repo
 */
public final class Main {
  private static final String USAGE = String.join("\n",
      "usage:",
      "  ask \"<question>\"",
      "  investigate \"<title>\" [\"<description>\"]",
      "  skills list | zip [skill...] | installed",
      "  skills install <skill...>|--all [--from-github] [--include-examples] [--include-third-party]");

  private Main() {}

  private static final List<String> FLAGS =
      List.of("--all", "--from-github", "--include-examples", "--include-third-party");

  public static void main(String[] args) {
    int code;
    try {
      code = run(args);
    } catch (UsageException e) {
      code = usage(e.getMessage());
    } catch (Exception e) {
      Throwable c = e.getCause() != null && e instanceof java.util.concurrent.CompletionException ? e.getCause() : e;
      System.err.println(c.getClass().getSimpleName() + ": " + c.getMessage());
      code = 1;
    }
    System.exit(code);
  }

  /** Bad command line: print the message and the usage, exit 2. */
  static final class UsageException extends RuntimeException {
    UsageException(String msg) {
      super(msg);
    }
  }

  static String region() {
    String r = System.getenv("AWS_REGION");
    if (r == null || r.isEmpty()) r = System.getenv("AWS_DEFAULT_REGION");
    return r == null || r.isEmpty() ? "us-east-1" : r;
  }

  static int run(String[] args) throws Exception {
    if (args.length == 0) return usage(null);
    String space = System.getenv("AGENT_SPACE_ID");
    Region region = Region.of(region());
    String cmd = args[0];

    if (cmd.equals("skills")) checkSkillArgs(Arrays.copyOfRange(args, 1, args.length));
    if (cmd.equals("skills") && args.length > 1 && (args[1].equals("list") || args[1].equals("zip"))) {
      return localSkills(args);
    }
    if (space == null || space.isEmpty()) throw new UsageException("set AGENT_SPACE_ID first");

    try (DevOpsAgentClient client = DevOpsAgentClient.builder().region(region).build()) {
      switch (cmd) {
        case "ask": {
          if (args.length < 2) return usage(null);
          try (DevOpsAgentAsyncClient async = DevOpsAgentAsyncClient.builder().region(region).build()) {
            QuickStart.ask(client, async, space, args[1], t -> { System.out.print(t); System.out.flush(); });
          }
          return 0;
        }
        case "investigate": {
          if (args.length < 2) return usage(null);
          QuickStart.investigate(client, space, args[1], args.length > 2 ? args[2] : "", 30_000,
              System.out::println);
          return 0;
        }
        case "skills":
          return remoteSkills(client, space, Arrays.copyOfRange(args, 1, args.length));
        default:
          return usage(null);
      }
    }
  }

  private static int localSkills(String[] args) throws Exception {
    Skills skills = Skills.locate();
    if (args[1].equals("list")) {
      for (String s : skills.all()) {
        System.out.printf("%-45s %s%s%n", s, String.join(",", skills.frontmatter(s).agentTypes()), Skills.tag(s));
      }
      return 0;
    }
    Path dist = skills.distDir();
    Files.createDirectories(dist);
    List<String> names = args.length > 2 ? Arrays.asList(args).subList(2, args.length) : skills.all();
    for (String s : names) {
      Path out = dist.resolve(s + ".zip");
      Files.write(out, skills.buildZip(s));
      System.out.println(out + "  " + Files.size(out) / 1024 + " KB");
    }
    return 0;
  }

  /** Same rules as the Python and Node.js versions: unknown options and typo skill names fail. */
  static void checkSkillArgs(String[] args) {
    if (args.length == 0) throw new UsageException(null);
    String sub = args[0];
    List<String> flags = new ArrayList<>();
    List<String> names = new ArrayList<>();
    for (String a : Arrays.copyOfRange(args, 1, args.length)) (a.startsWith("--") ? flags : names).add(a);
    List<String> bad = new ArrayList<>(flags);
    if (sub.equals("install")) bad.removeAll(FLAGS);
    if (!bad.isEmpty()) throw new UsageException("unknown option: " + String.join(" ", bad));
    if (sub.equals("zip") || sub.equals("install")) {
      List<String> unknown = new ArrayList<>(names);
      unknown.removeAll(Skills.locate().all());
      if (!unknown.isEmpty()) {
        throw new UsageException("unknown skills: " + String.join(", ", unknown) + " (see: skills list)");
      }
    }
    if (!List.of("list", "zip", "installed", "install").contains(sub)) throw new UsageException(null);
  }

  private static int remoteSkills(DevOpsAgentClient client, String space, String[] args) {
    if (args[0].equals("installed")) {
      Skills.installedNames(client, space).forEach((n, id) -> System.out.printf("%-45s %s%n", n, id));
      return 0;
    }
    Skills skills = Skills.locate();
    List<String> flags = new ArrayList<>();
    List<String> names = new ArrayList<>();
    for (String a : Arrays.copyOfRange(args, 1, args.length)) (a.startsWith("--") ? flags : names).add(a);
    List<String> chosen = names;
    if (flags.contains("--all")) {
      if (!names.isEmpty()) throw new UsageException("use either --all or skill names, not both");
      chosen = skills.defaults(flags.contains("--include-examples"), flags.contains("--include-third-party"));
      List<String> skipped = new ArrayList<>(skills.all());
      skipped.removeAll(chosen);
      if (!skipped.isEmpty()) {
        System.out.println("--all skips " + skipped.size() + " (examples / third-party): " + String.join(", ", skipped));
      }
    }
    if (chosen.isEmpty()) throw new UsageException("name skills or use --all");
    Map<String, String> results =
        skills.install(client, space, chosen, flags.contains("--from-github"), System.out::println);
    return results.containsValue("failed") ? 1 : 0;
  }

  private static int usage(String msg) {
    if (msg != null) System.err.println(msg);
    System.err.println(USAGE);
    return 2;
  }
}
