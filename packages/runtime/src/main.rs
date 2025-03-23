use simple_logger::SimpleLogger;
use tempfile::Builder;

use std::fs::File;
use std::io::Write;

use crate::io::Error;
use std::io;

use std::cmp::min;

use futures_util::StreamExt;
use indicatif::{ProgressBar, ProgressStyle};

async fn download_firefox_source(version: &str) -> Result<std::path::PathBuf, String> {
    log::debug!("Downloading firefox source code for version {}", version);

    std::fs::create_dir_all("engine").unwrap();

    let url = format!(
        "https://archive.mozilla.org/pub/firefox/releases/{}/source/firefox-{}.source.tar.xz",
        version, version
    );

    let tmp_dir = Builder::new().prefix("warpfox").tempdir().unwrap();
    let response = reqwest::get(&url)
        .await
        .or(Err(format!("Failed to GET from '{}'", &url)))?;

    let total_size = response
        .content_length()
        .ok_or(format!("Failed to get content length from '{}'", &url))
        .unwrap();

    // Indicatif setup
    let pb = ProgressBar::new(total_size);
    pb.set_style(ProgressStyle::default_bar()
        .template("{msg}\n{spinner:.green} [{elapsed_precise}] [{wide_bar:.cyan/blue}] {bytes}/{total_bytes} ({bytes_per_sec}, {eta})")
        .unwrap().progress_chars("#>-"));
    pb.set_message(format!("Downloading {}", url));

    let mut downloaded: u64 = 0;
    let mut stream = response.bytes_stream();

    let mut dest = {
        let fname = url
            .rsplit('/')
            .next()
            .ok_or(format!("Failed to get filename from '{}'", &url))
            .unwrap();

        let fname = tmp_dir.path().join(fname);
        File::create(fname).unwrap()
    };

    while let Some(item) = stream.next().await {
        let chunk = item.or(Err(format!("Error while downloading file")))?;
        dest.write_all(&chunk)
            .or(Err(format!("Error while writing to file")))
            .unwrap();
        let new = min(downloaded + (chunk.len() as u64), total_size);
        downloaded = new;
        pb.set_position(new);
    }

    pb.finish();
    Ok(tmp_dir.into_path())
}

fn unpack_firefox_source(
    source_tar: std::path::PathBuf,
) -> Result<std::path::PathBuf, std::io::Error> {
    log::debug!("Unpacking firefox source code");

    let output = std::path::PathBuf::from("engine");
    std::fs::create_dir_all(&output).unwrap();

    let mut cmd = std::process::Command::new("tar");
    cmd.arg("-xf")
        .arg(source_tar)
        .arg("--strip-components=1")
        .arg("-C")
        .arg(&output)
        .output()
        .expect("failed to execute process");

    Ok(output)
}

fn cleanup(source_tar_dir: &std::path::PathBuf) -> Result<(), std::io::Error> {
    log::info!("Cleaning up");
    // Remove directory
    std::fs::remove_dir_all(source_tar_dir).unwrap();
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    SimpleLogger::new()
        .with_colors(true)
        .without_timestamps()
        .init()
        .unwrap();

    let manifest: serde_json::Value =
        serde_json::from_str(include_str!("../../../firefox.json")).unwrap();
    let version = manifest["version"].as_str().unwrap();

    log::info!("Starting runtime for firefox v{}", version);
    let source_tar_dir = download_firefox_source(version).await.unwrap();
    let source_tar = source_tar_dir.join("firefox-".to_string() + version + ".source.tar.xz");
    log::info!("Downloaded source code to {:?}", source_tar);
    let source_dir = unpack_firefox_source(source_tar.clone()).unwrap();
    log::info!("Unpacked source code to {:?}", source_dir);

    cleanup(&source_tar_dir).unwrap();
    Ok(())
}
