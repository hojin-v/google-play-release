# Load the real lane definitions with a fake Publisher boundary. Never authenticates.
require "fastlane"
require "tmpdir"
require "json"
require "digest"
require "yaml"
require "open3"
UI = FastlaneCore::UI unless defined?(UI)

class LaneHarness
  attr_reader :lanes
  def initialize = @lanes = {}
  def opt_out_usage(*) = nil
  def default_platform(*) = nil
  def platform(_, &block) = instance_eval(&block)
  def desc(*) = nil
  def lane(name, &block) = @lanes[name] = block
end

def check(value, message)
  raise message unless value
end

def rejected(message = nil)
  begin
    yield
  rescue StandardError => error
    check(!message || error.message.include?(message), "Unexpected rejection: #{error.message}")
    return error
  end
  raise "Expected operation to be blocked"
end

Dir.mktmpdir do |root|
  require "fileutils"
  FileUtils.mkdir_p(File.join(root, "play/metadata/ko-KR/images/phoneScreenshots"))
  FileUtils.mkdir_p(File.join(root, "build"))
  File.write(File.join(root, "play/metadata/ko-KR/images/phoneScreenshots/01.png"), "fixture-image")
  config = {package_name: "com.example.other", output_path: "build/releases", metadata_path: "play/metadata", contact_email: "developer@example.com"}
  File.write(File.join(root, "play/release.json"), JSON.generate(config))
  credentials = File.join(root, "credentials.json")
  File.write(credentials, "{}")
  ENV["PLAY_PROJECT_ROOT"] = root
  harness = LaneHarness.new
  harness.instance_eval(File.read(File.join(__dir__, "Fastfile")), File.join(__dir__, "Fastfile"))
  auth = Google::Auth::ServiceAccountCredentials.singleton_class
  auth.alias_method(:original_make_creds_for_test, :make_creds)
  auth.define_method(:make_creds) { |**_| Object.new }
  audit = {"version_name" => "1.2", "version_code" => 12, "aab_sha256" => "candidate-hash"}
  image = Digest::SHA256.hexdigest("fixture-image")
  before = {package_name: "com.example.other", state: "committed", countries: ["KR"], rest_of_world: true,
    bundles: [{version_code: 11, sha256: "old-hash"}], phone_screenshots: {"ko-KR" => [{sha256: image}]},
    tracks: [{track: "production", releases: [{version_codes: ["11"], status: "completed"}]}]}
  after = Marshal.load(Marshal.dump(before))
  after[:bundles] << {version_code: 12, sha256: "candidate-hash"}
  after[:tracks][0][:releases] = [{version_codes: ["12"], status: "completed"}]
  receipt_path = File.join(root, "build/play-edit-status.json")
  output_path = File.join(root, "build/releases/1.2-12/submission-receipt.json")
  rollout = PlayReleaseRollout.options("1.0")

  def snapshots(harness, values)
    calls = []
    harness.define_singleton_method(:read_play_snapshot) { |_| calls << :read; values.shift || raise("unexpected extra snapshot") }
    calls
  end

  calls = snapshots(harness, [before, after])
  harness.with_play_transaction(credentials, "release", audit, rollout: rollout) do
    File.write(receipt_path, JSON.generate(package_name: "com.example.other", edit_id: "committed-1", status: "committed"))
  end
  receipt = JSON.parse(File.read(output_path))
  check(receipt["api_commit_succeeded"] && receipt["remote_verified"], "Write verified production receipt")
  check(!receipt["review_approval_verified"] && !receipt["public_update_verified"], "Never claim Google approval")
  check(calls.size == 2, "Read before and after exactly once")

  wrong = Marshal.load(Marshal.dump(after)); wrong[:bundles].last[:sha256] = "wrong"
  calls = snapshots(harness, [before, wrong])
  rejected("Remote AAB") do
    harness.with_play_transaction(credentials, "release", audit, rollout: rollout) do
      File.write(receipt_path, JSON.generate(package_name: "com.example.other", edit_id: "committed-2", status: "committed"))
    end
  end
  receipt = JSON.parse(File.read(output_path))
  check(receipt["api_commit_succeeded"] && !receipt["remote_verified"], "Commit success must not hide verification failure")
  check(calls.size == 2, "Verification failure must not upload/retry")

  staged = Marshal.load(Marshal.dump(after)); staged[:state] = "uncommitted-edit"
  calls = snapshots(harness, [before, staged])
  rejected("simulated upload failure") do
    harness.with_play_transaction(credentials, "release", audit, rollout: rollout) do
      File.write(receipt_path, JSON.generate(package_name: "com.example.other", edit_id: "preserve-this-edit", status: "pending_commit"))
      raise "simulated upload failure"
    end
  end
  receipt = JSON.parse(File.read(output_path))
  check(!receipt["api_commit_succeeded"] && !receipt["remote_verified"], "Failed upload cannot be reported saved")
  check(JSON.parse(File.read(receipt_path))["edit_id"] == "preserve-this-edit", "Preserve failed edit")
  check(calls.size == 2, "Failure must still read staged state once")

  snapshots(harness, [staged])
  rejected("unfinished edit") do
    harness.with_play_transaction(credentials, "release", audit, rollout: rollout) { raise "MUST NOT MUTATE" }
  end

  # All production entry points must reject missing consent before credentials/audit/API.
  harness.define_singleton_method(:play_credentials) { |**_| raise "MUST NOT READ CREDENTIALS" }
  [[:release, {}], [:resume, {}], [:promote, {version_code: 12, to: "production"}]].each do |name, options|
    rejected("Production blocked") { harness.lanes[name].call(options) }
  end
  rejected("explicit to:") { harness.lanes[:promote].call(version_code: 12) }
  rejected("shared") { harness.lanes[:sync_listing].call({}) }

  # An internal draft cannot update shared listing/contact or production.
  test_after = Marshal.load(Marshal.dump(before));test_after[:bundles] << {version_code: 12, sha256: "candidate-hash"}
  test_after[:tracks] << {track: "internal", releases: [{version_codes: ["12"], status: "draft"}]}
  snapshots(harness, [before, test_after])
  harness.define_singleton_method(:play_credentials) { |**_| credentials }
  harness.define_singleton_method(:audit_play_release) { |_, **_| audit }
  uploaded = nil
  harness.define_singleton_method(:upload_play_release) do |**options|
    uploaded = options
    File.write(receipt_path, JSON.generate(package_name: "com.example.other", edit_id: "internal-draft", status: "committed"))
  end
  harness.lanes[:draft].call(aab: "candidate.aab")
  check(uploaded[:track] == "internal" && uploaded[:release_status] == "draft", "Test upload is an internal draft")
  check(uploaded[:skip_upload_metadata] && uploaded[:skip_upload_images] && uploaded[:skip_upload_screenshots] && uploaded[:update_contact] == false,
        "Do not change shared production listing/contact during testing")
  check(!uploaded[:allow_automatic_review], "Automatic review fallback is not inferred")
  # Preserve the upstream first-production-draft path without granting delivery.
  first_before = Marshal.load(Marshal.dump(before))
  first_before[:bundles] << {version_code: 12, sha256: "candidate-hash"}
  first_before[:tracks][0][:releases] = []
  first_before[:tracks] << {track: "internal", releases: [{version_codes: ["12"], status: "draft"}]}
  first_after = Marshal.load(Marshal.dump(first_before))
  first_after[:tracks][0][:releases] = [{version_codes: ["12"], status: "draft"}]
  snapshots(harness, [first_before, first_after])
  harness.define_singleton_method(:google_play_track_version_codes) { |**_| [12] }
  harness.define_singleton_method(:production_gate) { |_| raise "MUST NOT AUTHORIZE DELIVERY FOR A DRAFT" }
  harness.lanes[:promote].call(aab: "candidate.aab", version_code: 12, from: "internal", to: "production", release_status: "draft")
  check(uploaded[:release_status] == "draft" && uploaded[:track_promote_release_status] == "draft" && !uploaded.key?(:rollout),
        "Initial production save must remain a draft, without rollout")
  check(uploaded[:changes_not_sent_for_review] && !uploaded[:allow_automatic_review] && !uploaded[:deactivate_on_promote] && !uploaded[:update_contact],
        "Do not auto-review, deactivate tests, or change contact for an initial draft")
  rejected("omit rollout") do
    harness.lanes[:promote].call(aab: "candidate.aab", version_code: 12, from: "internal", to: "production", release_status: "draft", rollout: "1.0")
  end
  rejected("Acknowledge shared") do
    harness.lanes[:promote].call(aab: "candidate.aab", version_code: 12, from: "internal", to: "production", include_listing: "true")
  end
  rejected("production delivery") do
    harness.lanes[:promote].call(aab: "candidate.aab", version_code: 12, from: "internal", to: "beta", include_listing: "true", acknowledge_shared_listing: "true")
  end
  candidate = Marshal.load(Marshal.dump(before))
  candidate[:bundles] << {version_code: 12, sha256: "candidate-hash"}
  candidate[:tracks] << {track: "internal", releases: [{version_codes: ["12"], status: "draft"}]}
  promoted = Marshal.load(Marshal.dump(candidate))
  promoted[:tracks][0][:releases] = [{version_codes: ["12"], status: "completed"}]
  gates = []
  harness.define_singleton_method(:production_gate) { |options| gates << options; audit }
  harness.define_singleton_method(:sh) { |*_, **_| "" }
  snapshots(harness, [candidate, promoted])
  harness.lanes[:promote].call(aab: "candidate.aab", version_code: 12, from: "internal", to: "production", rollout: "1.0", include_listing: "true", acknowledge_shared_listing: "true")
  check(gates.length == 1, "Combined listing promotion must retain the production artifact gate")
  check(uploaded[:skip_upload_aab] && uploaded[:skip_upload_apk], "Promote the tested file without reupload")
  check(!uploaded[:skip_upload_metadata] && !uploaded[:skip_upload_images] && !uploaded[:skip_upload_screenshots] && !uploaded[:skip_upload_changelogs], "Explicit combined promotion includes the approved listing and notes")
  check(uploaded[:metadata_path] == File.join(root, config[:metadata_path]) && uploaded[:track_promote_to] == "production", "Use this app's listing in the same production edit")
  snapshots(harness, [candidate, promoted])
  harness.lanes[:promote].call(aab: "candidate.aab", version_code: 12, from: "internal", to: "production", rollout: "1.0")
  check(uploaded[:skip_upload_metadata] && uploaded[:skip_upload_screenshots] && uploaded[:skip_upload_changelogs], "Default promotion keeps the existing listing")
  auth.alias_method(:make_creds, :original_make_creds_for_test)
end
puts "16 lane transaction and authorization cases passed (fake Publisher only)"

workflow = YAML.load_file(File.join(__dir__, "../.github/workflows/android-play-release.yml"))
steps = workflow.fetch("jobs").fetch("release").fetch("steps")
steps.select { |step| step["run"] }.each do |step|
  _, error, status = Open3.capture3("bash", "-n", stdin_data: step["run"])
  check(status.success?, "Workflow shell syntax: #{step['name']}: #{error}")
end
build = steps.find { |step| step["name"] == "Build and audit the signed test candidate" }
check(build["if"].include?("!= 'release'") && build["if"].include?("!= 'promote'"), "Production never rebuilds")
download = steps.find { |step| step["uses"].to_s.start_with?("actions/download-artifact") }
check(download.dig("with", "run-id").include?("candidate_run_id"), "Download the selected preparation run")
gate = steps.index { |step| step["name"] == "Select exact approved artifacts and check production gate" }
credentials = steps.index { |step| step["name"] == "Execute requested operation" }
check(gate < credentials, "Gate precedes Publisher credentials")
puts "Workflow candidate reuse, early guard and shell syntax passed"
